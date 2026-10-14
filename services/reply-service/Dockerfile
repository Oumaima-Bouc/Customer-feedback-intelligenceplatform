# Reply Service — Group Reply dispatcher
# Multi-stage, non-root, Consul-aware (mirrors ai-service-b).
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY services/reply-service/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
LABEL description="Group Reply dispatcher — reply-service"
RUN groupadd --gid 1001 replier \
 && useradd --uid 1001 --gid replier --no-create-home replier
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/reply-service/src/ ./src/
COPY services/reply-service/entrypoint.py .
COPY shared/ shared/

ENV PYTHONPATH=/app/src:/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /logs && chmod 1777 /logs
USER replier
EXPOSE 8083
HEALTHCHECK NONE
CMD ["python", "entrypoint.py"]
