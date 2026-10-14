# AI Service A — Topic Extraction Pipeline
# Multi-stage, non-root, Consul-aware
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev && rm -rf /var/lib/apt/lists/*
COPY services/ai-service-a/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# hdbscan installed offline from the vendored Linux cp312 wheel (deps already present).
COPY wheels/ /build/wheels/
RUN pip install --no-cache-dir --no-index --no-deps --find-links=/build/wheels hdbscan==0.8.40

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 postgresql-client && rm -rf /var/lib/apt/lists/*
RUN groupadd -r appgroup && useradd -r -g appgroup -s /sbin/nologin appuser
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/ai-service-a/src/ src/
COPY services/ai-service-a/config/ config/
COPY services/ai-service-a/process_system.py .
COPY services/ai-service-a/entrypoint.py .
COPY shared/ shared/
COPY migrations/topic_extraction/ /app/topic_migrations/

RUN mkdir -p /app/models /tmp/topic-extraction /tmp/huggingface /tmp/numba_cache /logs \
 && chown -R appuser:appgroup /app /tmp/topic-extraction /tmp/huggingface /tmp/numba_cache \
 && chmod 1777 /logs
# Creating /tmp/huggingface owned by appuser means the hf-cache named volume
# initialises with appuser ownership (so the embedding model can be written).
USER appuser

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/tmp/huggingface \
    TRANSFORMERS_CACHE=/tmp/huggingface \
    NUMBA_CACHE_DIR=/tmp/numba_cache

EXPOSE 8080
HEALTHCHECK NONE
CMD ["python", "entrypoint.py"]
