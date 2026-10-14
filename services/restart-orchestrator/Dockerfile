# Restart Orchestrator — Rolling restart coordinator
FROM python:3.12-slim
WORKDIR /app
COPY services/restart-orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/restart-orchestrator/app/ app/
COPY shared/ shared/

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8082
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
