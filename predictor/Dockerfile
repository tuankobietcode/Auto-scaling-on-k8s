# predictor/Dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY predictor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build context phải là thư mục gốc Manifest/ để các COPY bên dưới hợp lệ.
# Lệnh build đúng (chạy từ thư mục Manifest/):
#   docker build -f predictor/Dockerfile -t <dockerhub-user>/predictor:v1 .
COPY model/gru_cpu_model.keras  /app/gru_cpu_model.keras
COPY model/scaler.pkl           /app/scaler.pkl
COPY model/model_config.json    /app/model_config.json
COPY predictor/predictor.py     /app/predictor.py

RUN useradd -m -u 1000 predictor
USER predictor

ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "/app/predictor.py"]
