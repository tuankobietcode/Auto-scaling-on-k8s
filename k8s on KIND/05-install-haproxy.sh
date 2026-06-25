#!/usr/bin/env bash
# ============================================================================
# 05-install-haproxy.sh
# Chạy CHỈ trên VM HAProxy (Load Balancer) — Ubuntu 22.04.
# VM này KHÔNG join cluster, KHÔNG cần containerd/kubeadm.
#
# - Cài haproxy
# - Sinh /etc/haproxy/haproxy.cfg từ haproxy/haproxy.cfg.tmpl (thay IP worker)
# - Khởi động + bật service
#
# Dùng:
#   source 00-vars.env            # nạp WORKER1_IP, WORKER2_IP, WEB_NODEPORT
#   sudo -E bash 05-install-haproxy.sh
# ============================================================================
set -euo pipefail

WORKER1_IP="${WORKER1_IP:?Chưa set WORKER1_IP — source 00-vars.env}"
WORKER2_IP="${WORKER2_IP:?Chưa set WORKER2_IP — source 00-vars.env}"
WEB_NODEPORT="${WEB_NODEPORT:-30080}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPL="${SCRIPT_DIR}/haproxy/haproxy.cfg.tmpl"

echo "==> [1/3] Cài haproxy + gettext-base (cho envsubst)"
apt-get update -y
apt-get install -y haproxy gettext-base

echo "==> [2/3] Sinh /etc/haproxy/haproxy.cfg (worker1=${WORKER1_IP}, worker2=${WORKER2_IP}, port=${WEB_NODEPORT})"
export WORKER1_IP WORKER2_IP WEB_NODEPORT
envsubst '${WORKER1_IP} ${WORKER2_IP} ${WEB_NODEPORT}' \
  <"${TMPL}" >/etc/haproxy/haproxy.cfg

echo "==> Kiểm tra cú pháp cấu hình"
haproxy -c -f /etc/haproxy/haproxy.cfg

echo "==> [3/3] Khởi động lại + bật haproxy"
systemctl restart haproxy
systemctl enable haproxy
systemctl --no-pager status haproxy | head -n 5

echo ""
echo "============================================================"
echo " HAProxy đã chạy."
echo "   Web (người dùng): http://${HAPROXY_IP:-<HAPROXY_IP>}/"
echo "   Trang stats     : http://${HAPROXY_IP:-<HAPROXY_IP>}:8404/"
echo ""
echo " LƯU Ý: backend trỏ tới NodePort ${WEB_NODEPORT}. Cần áp"
echo " 99-carserv-nodeport-patch.yaml để carserv-svc mở NodePort này."
echo "============================================================"
