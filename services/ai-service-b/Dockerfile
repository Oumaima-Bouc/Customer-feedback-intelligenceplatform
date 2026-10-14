# AI Service B — Meta Scraper
# Multi-stage, non-root, Consul-aware
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY services/ai-service-b/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
LABEL description="Meta Page Comment Scraper — AI Service B"
RUN groupadd --gid 1001 scraper \
 && useradd --uid 1001 --gid scraper --no-create-home scraper
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/ai-service-b/src/ ./src/
COPY services/ai-service-b/entrypoint.py .
COPY shared/ shared/
COPY migrations/scraper/ /app/migrations/

ENV PYTHONPATH=/app/src:/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /logs && chmod 1777 /logs
USER scraper
EXPOSE 8081
HEALTHCHECK NONE
CMD ["python", "entrypoint.py"]
