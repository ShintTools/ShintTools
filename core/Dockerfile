FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir fastapi==0.111.0 uvicorn==0.30.1 pydantic==2.7.1 pytest==8.2.0 httpx==0.27.0 transformers==4.41.0 opencv-python-headless==4.9.0.80

RUN pip install --no-cache-dir torch==2.3.0+cpu --index-url https://download.pytorch.org/whl/cpu

COPY . .

EXPOSE 18200

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:18200/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "18200"]