#!/usr/bin/env bash
# ============================================================================
# 02-master-init.sh
# Chạy CHỈ trên MASTER node, SAU khi đã chạy 01-common-prereqs.sh ở đó.
#
# - kubeadm init (control plane)
# - cấu hình kubeconfig cho user thường
# - cài CNI Calico
# - xuất lệnh "kubeadm join" để dùng cho 2 worker
#
# Dùng:
#   source ../cluster-setup/00-vars.env   # nạp MASTER_IP, POD_CIDR, CALICO_VERSION...
#   sudo -E bash 02-master-init.sh        # -E để giữ biến môi trường
# ============================================================================
set -euo pipefail

MASTER_IP="${MASTER_IP:?Chưa set MASTER_IP — hãy source 00-vars.env trước}"
POD_CIDR="${POD_CIDR:-10.244.0.0/16}"
SVC_CIDR="${SVC_CIDR:-10.96.0.0/12}"
CALICO_VERSION="${CALICO_VERSION:-v3.28.0}"
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME="$(eval echo "~${REAL_USER}")"

echo "==> [1/4] kubeadm init (apiserver advertise = ${MASTER_IP}, podCIDR = ${POD_CIDR})"
kubeadm init \
  --apiserver-advertise-address="${MASTER_IP}" \
  --pod-network-cidr="${POD_CIDR}" \
  --service-cidr="${SVC_CIDR}" \
  --cri-socket="unix:///run/containerd/containerd.sock"

echo "==> [2/4] Cấu hình kubeconfig cho user ${REAL_USER}"
mkdir -p "${REAL_HOME}/.kube"
cp -f /etc/kubernetes/admin.conf "${REAL_HOME}/.kube/config"
chown "$(id -u "${REAL_USER}")":"$(id -g "${REAL_USER}")" "${REAL_HOME}/.kube/config"
export KUBECONFIG=/etc/kubernetes/admin.conf

echo "==> [3/4] Cài CNI Calico ${CALICO_VERSION} (tigera-operator)"
kubectl create -f \
  "https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/tigera-operator.yaml"

# Custom resource cấu hình IP pool khớp POD_CIDR
cat <<EOF | kubectl apply -f -
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    ipPools:
      - blockSize: 26
        cidr: ${POD_CIDR}
        encapsulation: VXLANCrossSubnet
        natOutgoing: Enabled
        nodeSelector: all()
---
apiVersion: operator.tigera.io/v1
kind: APIServer
metadata:
  name: default
spec: {}
EOF

echo "==> [4/4] Sinh lệnh join cho worker (lưu vào /tmp/kubeadm-join.sh)"
kubeadm token create --print-join-command --ttl 24h | tee /tmp/kubeadm-join.sh
chmod +x /tmp/kubeadm-join.sh

echo ""
echo "============================================================"
echo " MASTER đã sẵn sàng. Theo dõi tới khi mọi pod Running:"
echo "   kubectl get nodes -o wide"
echo "   kubectl get pods -A -w"
echo ""
echo " Copy nội dung /tmp/kubeadm-join.sh sang 2 worker rồi chạy"
echo " (hoặc dán vào 03-worker-join.sh). Lệnh có dạng:"
echo "   kubeadm join ${MASTER_IP}:6443 --token <...> \\"
echo "       --discovery-token-ca-cert-hash sha256:<...>"
echo "============================================================"
