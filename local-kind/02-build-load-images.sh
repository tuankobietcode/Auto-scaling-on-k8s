#!/usr/bin/env bash
# ============================================================================
# 02-build-load-images.sh — Build image predictor (GRU) + nạp vào cụm kind.
# kind chạy trong container riêng, KHÔNG thấy image trên Docker host trừ khi
# ta "kind load docker-image". Đó là điểm khác biệt chính so với chạy trên VM.
#
# Chạy từ thư mục Manifest/ (build context của predictor là Manifest/):
#   cd ../        # về thư mục Manifest/
#   bash local-kind/02-build-load-images.sh
# ============================================================================
set -euo pipefail

CLUSTER=datn
PREDICTOR_IMAGE="datn/predictor:v1"

# --- 1) Predictor (GRU) ---
echo "==> Build ${PREDICTOR_IMAGE} (context = thư mục Manifest/) ..."
docker build -f predictor/Dockerfile -t "${PREDICTOR_IMAGE}" .

echo "==> Nạp ${PREDICTOR_IMAGE} vào cụm kind '${CLUSTER}' ..."
kind load docker-image "${PREDICTOR_IMAGE}" --name "${CLUSTER}"

# --- 2) Web service (carserv) ---
# Nếu bạn ĐÃ có image web service riêng, build/nạp tương tự:
#   docker build -t datn/carserv:v1 /duong/dan/toi/web-app
#   kind load docker-image datn/carserv:v1 --name ${CLUSTER}
#
# Nếu CHƯA có app thật và chỉ cần một workload để autoscale demo, có thể dùng
# image mẫu sinh tải CPU của Kubernetes (không cần build):
#   docker pull registry.k8s.io/hpa-example
#   kind load docker-image registry.k8s.io/hpa-example --name ${CLUSTER}
#   -> rồi điền image này vào 05-carserv-webservice.yaml

echo ""
echo "==> Đã nạp image. Kiểm tra trong cụm:"
docker exec ${CLUSTER}-control-plane crictl images | grep -E "predictor|carserv" || true
echo ""
echo "Nhớ điền image vào 05-carserv-webservice.yaml (<IMAGE>) và 07-predictor.yaml (<PREDICTOR_IMAGE> = ${PREDICTOR_IMAGE})."
