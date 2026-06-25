# Build: docker build -f local-kind/testbed/k6/Dockerfile -t datn/cpuapp:v1 local-kind/testbed/k6
# (base python:3.10-slim đã cache local nên không cần mạng)
FROM python:3.10-slim
WORKDIR /app
COPY cpuapp.py /app/cpuapp.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/cpuapp.py"]
