#!/usr/bin/env bash
# ============================================================================
# 04-label-nodes.sh
# Chạy trên MASTER (có kubeconfig), SAU khi cả 2 worker đã Ready.
#
# Gắn nhãn để map đúng Biểu đồ triển khai:
#   - Worker 1 = "management" : nơi chạy AI scaler (predictor), Prometheus,
#                               Pushgateway, Grafana, kube-state-metrics + web service.
#   - Worker 2 = "workload"   : chỉ chạy các pod web service.
#
# Nhãn dùng: node-role=management / node-role=workload
# Sau đó dùng nodeSelector trong manifest để ghim pod (xem 05-pin-pods-note.md).
# ============================================================================
set -euo pipefail

WORKER1_HOST="${WORKER1_HOST:?Chưa set WORKER1_HOST — source 00-vars.env}"
WORKER2_HOST="${WORKER2_HOST:?Chưa set WORKER2_HOST — source 00-vars.env}"

echo "==> Gắn nhãn ${WORKER1_HOST} = management"
kubectl label node "${WORKER1_HOST}" node-role=management --overwrite
# Nhãn role hiển thị đẹp trong 'kubectl get nodes'
kubectl label node "${WORKER1_HOST}" node-role.kubernetes.io/management= --overwrite

echo "==> Gắn nhãn ${WORKER2_HOST} = workload"
kubectl label node "${WORKER2_HOST}" node-role=workload --overwrite
kubectl label node "${WORKER2_HOST}" node-role.kubernetes.io/workload= --overwrite

echo ""
echo "==> Kết quả:"
kubectl get nodes -o wide --show-labels | sed 's/,/\n      /g'
echo ""
echo "Tiếp theo: áp nodeSelector cho pod quản lý (xem 05-pin-pods-note.md)."
