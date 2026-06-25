#!/usr/bin/env bash
# ============================================================================
# restart-after-reboot.sh — Khởi động lại toàn bộ demo sau khi BẬT LẠI MÁY.
#
# Sau reboot: cụm kind + các pod (predictor, monitoring) thường TỰ lên lại khi
# Docker Desktop khởi động. Thứ KHÔNG tự lên là INJECTOR (tiến trình WSL) — script
# này lo phần đó + kiểm tra mọi thứ đã sẵn sàng.
#
# Cách dùng (trong WSL, SAU khi Docker Desktop đã "Engine running"):
#   bash local-kind/restart-after-reboot.sh
# ============================================================================
cd "$(dirname "$0")/.."   # về thư mục Manifest/

# >>> Đổi dòng này nếu muốn dùng sóng thay vì replay dữ liệu thật:
INJECT_CMD='python3 local-kind/testbed/inject_testbed.py replay --interval 300 --loop'
# Ví dụ sóng: INJECT_CMD='python3 local-kind/testbed/inject_testbed.py wave --low 5 --high 130 --period 1800 --interval 30'

echo "==> [1/6] Kiểm tra Docker..."
if ! docker info >/dev/null 2>&1; then
  echo "    ✗ Docker chưa sẵn sàng. Mở Docker Desktop trên Windows, đợi 'Engine running' rồi chạy lại."
  exit 1
fi
echo "    ✓ Docker OK"

echo "==> [2/6] Kiểm tra cụm kind 'datn'..."
if ! kind get clusters 2>/dev/null | grep -q '^datn$'; then
  echo "    ✗ Không thấy cụm 'datn'. Có thể cụm đã bị xoá — dựng lại bằng:"
  echo "        bash local-kind/01-create-cluster.sh && bash local-kind/02-build-load-images.sh && bash local-kind/03-deploy.sh"
  exit 1
fi
echo "    ✓ Cụm tồn tại"

echo "==> [3/6] Đợi node Ready (có thể mất 1-3 phút sau reboot)..."
kubectl wait --for=condition=Ready nodes --all --timeout=240s

echo "==> [4/6] Đợi các dịch vụ Running..."
kubectl -n carserv    rollout status deploy/predictor  --timeout=240s
kubectl -n monitoring rollout status deploy/prometheus --timeout=240s
kubectl -n monitoring rollout status deploy/grafana    --timeout=180s

echo "==> [5/6] Đảm bảo predictor ở chế độ testbed..."
kubectl -n carserv set env deploy/predictor TESTBED_MODE=true INTERVAL_SEC=300 >/dev/null
echo "    ✓ TESTBED_MODE=true, INTERVAL_SEC=300"

echo "==> [6/6] Khởi động injector..."
if pgrep -f inject_testbed >/dev/null; then
  echo "    ✓ Injector đã chạy sẵn (PID $(pgrep -f inject_testbed | tr '\n' ' '))"
else
  nohup $INJECT_CMD > /tmp/injector.log 2>&1 &
  sleep 2
  if pgrep -f inject_testbed >/dev/null; then
    echo "    ✓ Đã khởi động injector (log: /tmp/injector.log)"
  else
    echo "    ✗ Injector không khởi động được — xem /tmp/injector.log"
  fi
fi

echo ""
echo "================ TRẠNG THÁI ================"
kubectl get pods -n carserv -o wide | grep -E 'predictor|carserv-deploy'
kubectl get scaledobject,hpa -n carserv 2>/dev/null
echo ""
echo "Grafana    : http://localhost:30030  (admin/admin123)"
echo "Prometheus : http://localhost:30090"
echo "Web        : http://localhost:30080"
echo ""
echo "LƯU Ý: Prometheus dùng emptyDir nên LỊCH SỬ metric đã MẤT sau reboot."
echo "       Biểu đồ Grafana bắt đầu lại từ 0 — để injector chạy một lúc cho dữ liệu tích lũy lại."
