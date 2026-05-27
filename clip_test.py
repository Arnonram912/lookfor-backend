# clip_test.py
from PIL import Image
import numpy as np
import json
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


def _center_crop(image: Image.Image, crop_ratio: float = 0.85) -> Image.Image:
    width, height = image.size
    crop_width = max(1, int(width * crop_ratio))
    crop_height = max(1, int(height * crop_ratio))
    left = max(0, (width - crop_width) // 2)
    top = max(0, (height - crop_height) // 2)
    return image.crop((left, top, left + crop_width, top + crop_height)).convert("RGB")


def _build_image_views(image: Image.Image) -> list[Image.Image]:
    base = image.convert("RGB")
    return [
        base,
        _center_crop(base, 0.9),
        _center_crop(base, 0.75),
        base.transpose(Image.FLIP_LEFT_RIGHT),
    ]


def _encode_image_views(images: list[Image.Image]) -> np.ndarray:
    model_obj, processor_obj = get_clip_components()
    inputs = processor_obj(images=images, return_tensors="pt", padding=True)

    with torch.no_grad():
        feat = model_obj.get_image_features(**inputs)
        if hasattr(feat, "pooler_output"):
            feat = feat.pooler_output
        feat = feat / feat.norm(p=2, dim=-1, keepdim=True)

    averaged = feat.mean(dim=0, keepdim=True)
    averaged = averaged / averaged.norm(p=2, dim=-1, keepdim=True)
    return averaged.cpu().numpy().flatten()


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
    image_embeddings = [get_image_embedding(image) for image in images if image is not None]
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

    img = Image.open(image_path).convert("RGB")
    model_obj, processor_obj = get_clip_components()
    
    # We provide the image AND the text labels to the processor
    inputs = processor_obj(text=categories, images=img, return_tensors="pt", padding=True)

    with torch.no_grad():
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
    for item in db_items:
        if item.image_embedding:
            # 2. Convert stored JSON string back to a numpy array
            dataset_vec = np.array(json.loads(item.image_embedding)).flatten()
            
            # 3. Calculate similarity (Dot product works because vectors are normalized)
            score = float(np.dot(search_vec, dataset_vec))
            
            matches.append({
                "id": item.id,
                "category": item.category,
                "score": float(score)
            })

    # Sort by highest score first
    return sorted(matches, key=lambda x: x['score'], reverse=True)

def get_text_embedding(text):
    model_obj, processor_obj = get_clip_components()
    inputs = processor_obj(text=[text], return_tensors="pt", padding=True)

    with torch.no_grad():
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
    text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

    return text_features.cpu().numpy().flatten()

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
        print("🚀 Loading CLIP Model (this happens only once)...")
        _model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model = _model
        processor = _processor
    return _model, _processor
