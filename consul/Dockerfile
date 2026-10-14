FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir python-consul2==0.1.5
COPY consul/bootstrap/seed_kv.py .
CMD ["python", "seed_kv.py"]
