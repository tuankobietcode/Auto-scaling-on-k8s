#!/usr/bin/env bash
# ============================================================================
# 03-worker-join.sh
# Chạy trên MỖI worker (WORKER1 và WORKER2), SAU khi đã chạy 01-common-prereqs.sh.
#
# Dán lệnh join in ra từ 02-master-init.sh (file /tmp/kubeadm-join.sh trên master)
# vào biến JOIN_CMD bên dưới, rồi chạy:
#   sudo bash 03-worker-join.sh
#
# Hoặc copy thẳng /tmp/kubeadm-join.sh từ master sang worker rồi:
#   sudo bash /tmp/kubeadm-join.sh
# ============================================================================
set -euo pipefail

# >>> DÁN LỆNH JOIN THẬT VÀO ĐÂY (lấy từ master) <<<
JOIN_CMD='kubeadm join <MASTER_IP>:6443 --token <TOKEN> --discovery-token-ca-cert-hash sha256:<HASH>'

if [[ "${JOIN_CMD}" == *"<MASTER_IP>"* ]]; then
  echo "LỖI: bạn chưa dán lệnh join thật vào biến JOIN_CMD." >&2
  echo "Lấy lệnh trên master bằng:  kubeadm token create --print-join-command" >&2
  exit 1
fi

echo "==> Join node $(hostname) vào cluster..."
eval "sudo ${JOIN_CMD} --cri-socket=unix:///run/containerd/containerd.sock"

echo ""
echo "==> Đã gửi yêu cầu join. Trên MASTER kiểm tra:"
echo "    kubectl get nodes -o wide   (đợi tới khi node Ready)"
