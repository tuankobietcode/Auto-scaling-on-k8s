#!/usr/bin/env bash
# ============================================================================
# 03-deploy.sh — Apply toàn bộ stack lên cụm kind + ghim pod đúng node.
# Chạy từ thư mục Manifest/  (vì tham chiếu tới ./k8s/):
#   bash local-kind/03-deploy.sh
#
# YÊU CẦU TRƯỚC KHI CHẠY:
#   - Đã chạy 01-create-cluster.sh (cụm Ready, KEDA Running)
#   - Đã chạy 02-build-load-images.sh (image đã nạp vào kind)
#   - Đã ĐIỀN image vào k8s/05-carserv-webservice.yaml và k8s/07-predictor.yaml
#   - Trong 07-predictor.yaml: đặt imagePullPolicy: IfNotPresent (image local từ kind)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/../k8s"

echo "==> Apply manifest theo thứ tự ..."
kubectl apply -f 00-namespaces.yaml
kubectl apply -f 01-kube-state-metrics.yaml
kubectl apply -f 02-prometheus.yaml
kubectl apply -f 03-pushgateway.yaml
kubectl apply -f 04-grafana.yaml
kubectl apply -f 05-carserv-webservice.yaml
kubectl apply -f 06-haproxy.yaml          # HAProxy TRONG cluster (NodePort 30080/30084)
kubectl apply -f 07-predictor.yaml
kubectl apply -f 08-keda-scaledobject.yaml

echo "==> Ghim pod quản lý vào worker1 (node-role=management) ..."
# predictor ở ns carserv; phần monitoring ở ns monitoring
kubectl -n carserv patch deploy predictor --type merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"node-role":"management"}}}}}' || true
for d in prometheus pushgateway grafana kube-state-metrics haproxy; do
  kubectl -n monitoring patch deploy "$d" --type merge \
    -p '{"spec":{"template":{"spec":{"nodeSelector":{"node-role":"management"}}}}}' 2>/dev/null \
    && echo "   pinned $d -> management" || true
done

echo "==> Ép web service chỉ chạy ở worker2 (node-role=workload) — đúng sơ đồ ..."
kubectl -n carserv patch deploy carserv-deploy --type merge \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"node-role":"workload"}}}}}' || true

echo ""
echo "==> Trạng thái:"
kubectl get pods -A -o wide | grep -E "carserv|monitoring|keda" || true
kubectl get scaledobject,hpa -n carserv || true
echo ""
echo "Truy cập (từ Windows, nhờ port mapping của kind):"
echo "  Web (HAProxy) : http://localhost:30080"
echo "  HAProxy stats : http://localhost:30084"
echo "  Prometheus    : http://localhost:30090"
echo "  Pushgateway   : http://localhost:30060"
echo "  Grafana       : http://localhost:30030"
