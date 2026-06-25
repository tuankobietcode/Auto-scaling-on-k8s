#!/usr/bin/env bash
# ============================================================================
# 01-create-cluster.sh — Dựng cụm kind 3 node + gắn nhãn + cài KEDA.
# Chạy trong WSL2 Ubuntu (hoặc Linux) đã có: docker, kind, kubectl.
# Vị trí: cd vào thư mục local-kind/ rồi: bash 01-create-cluster.sh
# ============================================================================
set -euo pipefail

# Luôn trỏ tới file config nằm cùng thư mục với script này (chạy từ đâu cũng được)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CLUSTER=datn
KEDA_VERSION=v2.14.0

echo "==> [1/4] Tạo cụm kind 3 node ..."
if kind get clusters | grep -q "^${CLUSTER}$"; then
  echo "    Cụm '${CLUSTER}' đã tồn tại, bỏ qua bước tạo."
else
  kind create cluster --config "${SCRIPT_DIR}/kind-cluster.yaml"
fi

echo "==> [2/4] Đợi tất cả node Ready ..."
kubectl wait --for=condition=Ready nodes --all --timeout=180s

echo "==> [3/4] Gắn nhãn hiển thị node-role.kubernetes.io (cho đẹp 'kubectl get nodes') ..."
# Nhãn node-role=management/workload đã set sẵn trong kind-cluster.yaml.
# Nhãn node-role.kubernetes.io/* phải do kubectl (control-plane) set, kubelet không được phép.
kubectl label node ${CLUSTER}-worker  node-role.kubernetes.io/management= --overwrite
kubectl label node ${CLUSTER}-worker2 node-role.kubernetes.io/workload=   --overwrite

echo "==> [4/4] Cài KEDA operator ${KEDA_VERSION} ..."
kubectl apply --server-side -f \
  https://github.com/kedacore/keda/releases/download/${KEDA_VERSION}/keda-${KEDA_VERSION}.yaml
echo "    Đợi keda-operator Running ..."
kubectl -n keda wait --for=condition=Available deploy/keda-operator --timeout=180s || true

echo ""
echo "==> Xong. Trạng thái node:"
kubectl get nodes -o wide
echo ""
echo "Bước tiếp theo: build + load image (bash 02-build-load-images.sh), rồi apply manifest."
