FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HF_HOME=/home/data/huggingface \
    TRANSFORMERS_CACHE=/home/data/huggingface \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2 \
    DB_POOL_SIZE=2 \
    DB_MAX_OVERFLOW=1 \
    ACCOUNT_EMAIL_QUEUE_SIZE=500 \
    CLIP_TORCH_THREADS=1 \
    CLIP_IMAGE_VIEWS=2 \
    CLIP_MAX_INPUT_DIMENSION=768

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r requirements.txt \
    && find /usr/local/lib/python3.11/site-packages \
        -type d \( -name tests -o -name test -o -name __pycache__ \) \
        -prune -exec rm -rf '{}' +

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --limit-concurrency ${UVICORN_LIMIT_CONCURRENCY:-20} --backlog ${UVICORN_BACKLOG:-64} --timeout-keep-alive 5"]
