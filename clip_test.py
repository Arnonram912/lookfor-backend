# clip_test.py
from PIL import Image
import numpy as np
import json
import os
import threading
from functools import lru_cache
# Load the model and processor only when an AI comparison endpoint needs them.
# This keeps normal pages from failing during app startup when the CLIP weights
# are not already cached locally.
torch = None
CLIPProcessor = None
CLIPModel = None
model = None
processor = None
_model = None
_processor = None
_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "openai/clip-vit-base-patch32")
_MODEL_LOAD_LOCK = threading.Lock()
_INFERENCE_LOCK = threading.Lock()
_MAX_INPUT_DIMENSION = max(224, int(os.getenv("CLIP_MAX_INPUT_DIMENSION", "1024")))
_IMAGE_VIEW_COUNT = max(1, min(4, int(os.getenv("CLIP_IMAGE_VIEWS", "2"))))


def _bounded_rgb_image(image: Image.Image) -> Image.Image:
    bounded = image.convert("RGB")
    if max(bounded.size) > _MAX_INPUT_DIMENSION:
        bounded.thumbnail(
            (_MAX_INPUT_DIMENSION, _MAX_INPUT_DIMENSION),
            Image.Resampling.LANCZOS,
        )
    return bounded


def _center_crop(image: Image.Image, crop_ratio: float = 0.85) -> Image.Image:
    width, height = image.size
    crop_width = max(1, int(width * crop_ratio))
    crop_height = max(1, int(height * crop_ratio))
    left = max(0, (width - crop_width) // 2)
    top = max(0, (height - crop_height) // 2)
    return image.crop((left, top, left + crop_width, top + crop_height)).convert("RGB")


def _build_image_views(image: Image.Image) -> list[Image.Image]:
    base = _bounded_rgb_image(image)
    return [
        base,
        _center_crop(base, 0.9),
        _center_crop(base, 0.75),
        base.transpose(Image.FLIP_LEFT_RIGHT),
    ][:_IMAGE_VIEW_COUNT]


def _encode_images(images: list[Image.Image]) -> np.ndarray:
    model_obj, processor_obj = get_clip_components()

    with _INFERENCE_LOCK, torch.inference_mode():
        # Serialize preprocessing too. Otherwise concurrent requests can each
        # allocate a large tensor batch while waiting for model inference.
        inputs = processor_obj(images=images, return_tensors="pt", padding=True)
        feat = model_obj.get_image_features(**inputs)
        if hasattr(feat, "pooler_output"):
            feat = feat.pooler_output
        feat = feat / feat.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-12)

    return feat.cpu().numpy()


def _average_normalized_features(features: np.ndarray) -> np.ndarray:
    averaged = np.mean(features, axis=0)
    norm = np.linalg.norm(averaged)
    return averaged if norm == 0 else averaged / norm


def _encode_image_views(images: list[Image.Image]) -> np.ndarray:
    return _average_normalized_features(_encode_images(images))


def get_image_embedding(image: Image.Image) -> np.ndarray:
    views = _build_image_views(image)
    return _encode_image_views(views)


def combine_embeddings(embeddings: list[np.ndarray]) -> np.ndarray:
    vectors = [np.asarray(embedding).flatten() for embedding in embeddings if embedding is not None]
    if not vectors:
        raise ValueError("At least one embedding is required.")

    averaged = np.mean(np.stack(vectors), axis=0)
    norm = np.linalg.norm(averaged)
    if norm == 0:
        return averaged
    return averaged / norm


def get_multi_image_embedding(images: list[Image.Image]) -> np.ndarray:
    valid_images = [image for image in images if image is not None]
    if not valid_images:
        raise ValueError("At least one image is required.")

    # Preserve the four-view averaging behavior, but execute every view from
    # every uploaded image in one model pass.
    views_per_image = [_build_image_views(image) for image in valid_images]
    view_count = len(views_per_image[0])
    features = _encode_images([view for views in views_per_image for view in views])
    image_embeddings = [
        _average_normalized_features(features[start:start + view_count])
        for start in range(0, len(features), view_count)
    ]
    return combine_embeddings(image_embeddings)

def get_similarity_score(image_path1, image_path2):
    # 1. Load images
    img1 = Image.open(image_path1).convert("RGB")
    img2 = Image.open(image_path2).convert("RGB")

    vec1 = get_image_embedding(img1)
    vec2 = get_image_embedding(img2)
    return float(np.dot(vec1, vec2))


def get_category_labels_from_db() -> list[str]:
    try:
        from database import SessionLocal
        import models

        db = SessionLocal()
        try:
            categories = db.query(models.Category).order_by(models.Category.name.asc()).all()
            labels = [str(category.name).strip() for category in categories if category and category.name and str(category.name).strip()]
            return labels
        finally:
            db.close()
    except Exception:
        return []


def describe_item(image_path, categories=None):
    if categories is None:
        categories = get_category_labels_from_db()

    if not categories:
        categories = ["wallet", "bag", "id card", "umbrella", "keys"]

    img = _bounded_rgb_image(Image.open(image_path))
    model_obj, processor_obj = get_clip_components()
    
    # We provide the image AND the text labels to the processor
    inputs = processor_obj(text=categories, images=img, return_tensors="pt", padding=True)

    with _INFERENCE_LOCK, torch.inference_mode():
        outputs = model_obj(**inputs)
        # CLIP calculates the "logits" (likelihood) for each text label
        logits_per_image = outputs.logits_per_image 
        probs = logits_per_image.softmax(dim=1) # Turn scores into percentages

    # Get the index of the highest probability
    best_match_idx = probs.argmax().item()
    description = categories[best_match_idx]
    confidence = probs[0][best_match_idx].item()

    return description, confidence

def find_matches_in_dataset(search_image_path, db_items):
    """
    search_image_path: path to the student's lost item photo
    db_items: list of rows from your 'items' table
    """
    # 1. Get embedding for the new search image
    search_img = Image.open(search_image_path).convert("RGB")
    search_vec = get_image_embedding(search_img)

    matches = []
    vectors = []
    for item in db_items:
        if item.image_embedding:
            try:
                dataset_vec = np.asarray(
                    json.loads(item.image_embedding), dtype=np.float32
                ).flatten()
                if dataset_vec.shape != search_vec.shape:
                    continue
                vectors.append(dataset_vec)
                matches.append({"id": item.id, "category": item.category})
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

    if vectors:
        scores = np.asarray(vectors, dtype=np.float32) @ search_vec.astype(np.float32)
        for match, score in zip(matches, scores):
            match["score"] = float(score)

    # Sort by highest score first
    return sorted(matches, key=lambda x: x['score'], reverse=True)

@lru_cache(maxsize=256)
def _get_text_embedding_cached(text: str) -> tuple[float, ...]:
    model_obj, processor_obj = get_clip_components()
    inputs = processor_obj(text=[text], return_tensors="pt", padding=True)

    with _INFERENCE_LOCK, torch.inference_mode():
        outputs = model_obj.get_text_features(**inputs)
        
        # FIX: Ensure we are working with the Tensor, not the Output object
        # If outputs is the object, we extract the features. 
        # get_text_features usually returns the tensor directly, 
        # but depending on your transformers version, it might be wrapped.
        text_features = outputs 
        
        if hasattr(text_features, "text_embeds"):
            text_features = text_features.text_embeds
        elif hasattr(text_features, "pooler_output"):
            text_features = text_features.pooler_output

    # Now .norm() will work because text_features is a torch.Tensor
    text_features = text_features / text_features.norm(
        p=2, dim=-1, keepdim=True
    ).clamp_min(1e-12)
    return tuple(text_features.cpu().numpy().flatten())


def get_text_embedding(text):
    return np.asarray(
        _get_text_embedding_cached(str(text)), dtype=np.float32
    ).copy()

def find_matches_by_text_details(category, location, date, db_items):
    text_query = f"A {category} found at {location} on {date}"
    
    # 1. This returns a 1D numpy array: e.g., shape (512,)
    text_vec = get_text_embedding(text_query)

    matches = []

    for item in db_items:
        if item.image_embedding:
            # 2. Load and ensure it is also a 1D array
            dataset_vec = np.array(json.loads(item.image_embedding)).flatten()

            # 3. FIX: Dot product of two 1D arrays is a scalar (a single float)
            # No need for .T or [0][0]
            score = float(np.dot(text_vec, dataset_vec))

            matches.append({
                "id": item.id,
                "category": item.category,
                "location": item.location,
                "score": score
            })

    # Sort by highest score first
    return sorted(matches, key=lambda x: x['score'], reverse=True)
def get_clip_components():
    """Lazy-loads the model and processor only when needed."""
    global model, processor, _model, _processor, torch, CLIPModel, CLIPProcessor
    if torch is None:
        import torch as torch_module
        torch = torch_module
    if CLIPModel is None or CLIPProcessor is None:
        from transformers import CLIPModel as clip_model_cls, CLIPProcessor as clip_processor_cls
        CLIPModel = clip_model_cls
        CLIPProcessor = clip_processor_cls
    if _model is None or _processor is None:
        with _MODEL_LOAD_LOCK:
            if _model is None or _processor is None:
                thread_count = int(os.getenv(
                    "CLIP_TORCH_THREADS", min(4, os.cpu_count() or 1)
                ))
                torch.set_num_threads(max(1, thread_count))
                try:
                    torch.set_num_interop_threads(1)
                except RuntimeError:
                    pass
                print(f"Loading CLIP model {_MODEL_NAME}...")
                _model = CLIPModel.from_pretrained(_MODEL_NAME)
                _model.eval()
                _processor = CLIPProcessor.from_pretrained(_MODEL_NAME)
                model = _model
                processor = _processor
    return _model, _processor
