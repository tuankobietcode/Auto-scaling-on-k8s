#!/usr/bin/env bash
# ============================================================================
# 01-common-prereqs.sh
# Chạy trên CẢ 3 node Kubernetes: MASTER, WORKER1, WORKER2.
# (KHÔNG chạy trên VM HAProxy — HAProxy dùng script riêng 05-install-haproxy.sh)
#
# Cài đặt: containerd + cấu hình kernel/sysctl + kubeadm/kubelet/kubectl.
# OS đích: Ubuntu 22.04 LTS.
#
# Dùng:
#   sudo bash 01-common-prereqs.sh
# (nhớ đã sửa K8S_VERSION / K8S_PKG_VERSION trong 00-vars.env nếu cần)
# ============================================================================
set -euo pipefail

K8S_VERSION="${K8S_VERSION:-1.30}"
K8S_PKG_VERSION="${K8S_PKG_VERSION:-1.30.4-1.1}"

echo "==> [1/7] Tắt swap (yêu cầu bắt buộc của kubelet)"
swapoff -a
# Vô hiệu hóa swap vĩnh viễn trong /etc/fstab
sed -i.bak -E 's/^([^#].*\sswap\s.*)$/#\1/' /etc/fstab

echo "==> [2/7] Nạp kernel module cần cho container networking"
cat <<'EOF' >/etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

echo "==> [3/7] Cấu hình sysctl cho bridged traffic + ip_forward"
cat <<'EOF' >/etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system >/dev/null

echo "==> [4/7] Cài containerd làm container runtime"
apt-get update -y
apt-get install -y ca-certificates curl gnupg apt-transport-https
install -m 0755 -d /etc/apt/keyrings

# Repo Docker để lấy containerd.io (ổn định trên Ubuntu)
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  >/etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y containerd.io

echo "==> [5/7] Cấu hình containerd dùng systemd cgroup driver"
mkdir -p /etc/containerd
containerd config default >/etc/containerd/config.toml
# Bật SystemdCgroup = true (bắt buộc khi kubelet dùng systemd cgroup driver)
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

echo "==> [6/7] Thêm repo pkgs.k8s.io và cài kubeadm/kubelet/kubectl ${K8S_PKG_VERSION}"
curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/Release.key" \
  | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/ /" \
  >/etc/apt/sources.list.d/kubernetes.list
apt-get update -y
apt-get install -y \
  kubelet="${K8S_PKG_VERSION}" \
  kubeadm="${K8S_PKG_VERSION}" \
  kubectl="${K8S_PKG_VERSION}"
# Ghim version để apt upgrade không tự nâng cấp đột ngột
apt-mark hold kubelet kubeadm kubectl
systemctl enable --now kubelet

echo "==> [7/7] Bật module ipvs (kube-proxy) — tùy chọn nhưng khuyến nghị"
apt-get install -y ipvsadm ipset
cat <<'EOF' >/etc/modules-load.d/ipvs.conf
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
EOF
modprobe ip_vs ip_vs_rr ip_vs_wrr ip_vs_sh nf_conntrack || true

echo ""
echo "==> HOÀN TẤT prereqs trên $(hostname)."
echo "    Kiểm tra: containerd active? -> systemctl is-active containerd"
echo "    Tiếp theo: chạy 02-master-init.sh trên MASTER, hoặc join trên WORKER."
