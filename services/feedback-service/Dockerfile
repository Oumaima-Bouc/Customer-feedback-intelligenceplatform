# Feedback Service — Label Feedback (human-in-the-loop correction)
# Multi-stage, non-root, Consul-aware (mirrors reply-service).
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY services/feedback-service/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
LABEL description="Label Feedback correction service — feedback-service"
RUN groupadd --gid 1001 feedback \
 && useradd --uid 1001 --gid feedback --no-create-home feedback
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/feedback-service/src/ ./src/
COPY services/feedback-service/entrypoint.py .
COPY shared/ shared/

ENV PYTHONPATH=/app/src:/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /logs && chmod 1777 /logs
USER feedback
EXPOSE 8084
HEALTHCHECK NONE
CMD ["python", "entrypoint.py"]
