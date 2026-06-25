# Dựng cụm Kubernetes: 1 Master + 2 Worker + 1 HAProxy

Bộ script/cấu hình để **dựng hạ tầng cụm** đúng theo *Biểu đồ triển khai*.
Phần này lo việc tạo cụm (kubeadm + containerd + Calico + HAProxy ngoài);
sau đó mới apply bộ manifest ứng dụng ở `../k8s/` (web service, predictor, Prometheus, KEDA…).

OS đích: **Ubuntu 22.04 LTS**. Container runtime: **containerd**. CNI: **Calico**.

## 1. Topology

```
                 ┌─────────────────────────┐
   Người dùng ──►│  HAProxy (Load Balancer) │  VM riêng, :80 + stats :8404
                 │     k8s-haproxy          │  KHÔNG join cluster
                 └────────────┬─────────────┘
                              │ round-robin → NodePort 30080
              ┌───────────────┼───────────────┐
              ▼                               ▼
   ┌────────────────────┐          ┌────────────────────┐
   │ Worker 1           │          │ Worker 2           │
   │ (management+work)  │          │ (workload)         │
   │ predictor / Prom / │          │ web service x N    │
   │ Grafana / web svc  │          │                    │
   └─────────┬──────────┘          └─────────┬──────────┘
             │  join 6443                     │  join 6443
             └───────────────┬───────────────┘
                             ▼
                  ┌────────────────────┐
                  │ Master (Control    │  kube-apiserver / etcd /
                  │ Plane) k8s-master  │  scheduler / controller-manager
                  └────────────────────┘
```

| Vai trò | Hostname | Biến IP | Cài gì |
|--------|----------|---------|--------|
| Load Balancer | `k8s-haproxy` | `HAPROXY_IP` | haproxy (script 05) |
| Control Plane | `k8s-master` | `MASTER_IP` | containerd + kubeadm (01 → 02) |
| Worker 1 (mgmt) | `k8s-worker1` | `WORKER1_IP` | containerd + kubeadm (01 → 03) |
| Worker 2 (work) | `k8s-worker2` | `WORKER2_IP` | containerd + kubeadm (01 → 03) |

## 2. Chuẩn bị (trên cả 4 VM)

Mỗi VM nên có: ≥2 vCPU, ≥2GB RAM (master/worker1 nên 4GB), IP tĩnh, mạng thông nhau.

```bash
# Đặt hostname cho từng máy (ví dụ trên master):
sudo hostnamectl set-hostname k8s-master

# Trên CẢ 4 VM, thêm bản ghi /etc/hosts (thay IP thật):
sudo tee -a /etc/hosts <<'EOF'
10.0.0.10  k8s-haproxy
10.0.0.11  k8s-master
10.0.0.12  k8s-worker1
10.0.0.13  k8s-worker2
EOF
```

Copy thư mục `cluster-setup/` này lên mỗi VM, rồi **điền IP thật vào `00-vars.env`**.

> OpenStack: mở Security Group cho các cổng — TCP `6443` (apiserver),
> `10250` (kubelet), `30000-32767` (NodePort), `179` (Calico BGP, nếu dùng),
> UDP `4789` (VXLAN), và `:80`/`:8404` trên VM HAProxy.

## 3. Các bước triển khai (theo thứ tự)

### Bước 1 — Prereqs trên 3 node K8s (master + 2 worker)
```bash
source 00-vars.env
sudo bash 01-common-prereqs.sh
```

### Bước 2 — Khởi tạo Master
```bash
# trên k8s-master
source 00-vars.env
sudo -E bash 02-master-init.sh
# Lệnh join được in ra & lưu ở /tmp/kubeadm-join.sh
kubectl get nodes      # master ở trạng thái Ready sau khi Calico Running
```

### Bước 3 — Join 2 Worker
```bash
# copy /tmp/kubeadm-join.sh từ master sang worker1 & worker2, rồi:
sudo bash /tmp/kubeadm-join.sh
# (hoặc dán lệnh vào 03-worker-join.sh và chạy)
```
Kiểm tra trên master: `kubectl get nodes -o wide` → cả 3 node `Ready`.

### Bước 4 — Gắn nhãn node (map đúng sơ đồ)
```bash
# trên master
source 00-vars.env
bash 04-label-nodes.sh
```

### Bước 5 — Cài HAProxy (trên VM k8s-haproxy)
```bash
source 00-vars.env
sudo -E bash 05-install-haproxy.sh
```

## 4. Triển khai ứng dụng lên cụm

Sau khi cụm Ready, sang `../k8s/` làm theo `../k8s/README.md`. Khác biệt khi
dùng HAProxy NGOÀI cluster:

1. Cài KEDA (1 lần) — như hướng dẫn ở `../k8s/README.md`.
2. Apply `00`→`05`, `07`, `08` như cũ. **BỎ QUA `06-haproxy.yaml`** (HAProxy đã ở VM riêng).
3. Áp NodePort cho web service để HAProxy ngoài trỏ vào:
   ```bash
   kubectl apply -f 99-carserv-nodeport-patch.yaml
   ```
4. Ghim pod quản lý vào worker1 theo `05-pin-pods-note.md` (nodeSelector).

Truy cập web: `http://<HAPROXY_IP>/` · stats HAProxy: `http://<HAPROXY_IP>:8404/`

## 5. Kiểm tra & gỡ lỗi nhanh

```bash
kubectl get nodes -o wide                 # 3 node Ready, role hiển thị đúng
kubectl get pods -A                        # calico-system, kube-system Running
kubectl get pods -A -o wide | grep worker  # pod nằm đúng node?

# HAProxy thấy backend UP chưa:  http://<HAPROXY_IP>:8404/
# Node chưa Ready thường do CNI: kubectl -n calico-system get pods
```

| Triệu chứng | Nguyên nhân thường gặp |
|-------------|------------------------|
| Node `NotReady` | Calico chưa Running / sysctl bridge chưa bật / firewall chặn VXLAN 4789 |
| `kubelet` không khởi động | Swap chưa tắt, hoặc cgroup driver lệch (containerd phải `SystemdCgroup=true`) |
| Worker join lỗi token | Token hết hạn → trên master: `kubeadm token create --print-join-command` |
| HAProxy backend `DOWN` | `99-carserv-nodeport-patch.yaml` chưa apply / web pod chưa Ready / SG chặn 30080 |

## 6. Reset (làm lại từ đầu nếu cần)
```bash
sudo kubeadm reset -f
sudo rm -rf /etc/cni/net.d ~/.kube
sudo systemctl restart containerd kubelet
```

## Cấu trúc thư mục
```
cluster-setup/
├── 00-vars.env                   # IP + version (ĐIỀN TRƯỚC)
├── 01-common-prereqs.sh          # chạy trên 3 node K8s
├── 02-master-init.sh             # chạy trên master
├── 03-worker-join.sh             # chạy trên mỗi worker
├── 04-label-nodes.sh             # chạy trên master
├── 05-install-haproxy.sh         # chạy trên VM HAProxy
├── 05-pin-pods-note.md           # hướng dẫn nodeSelector
├── 99-carserv-nodeport-patch.yaml# mở NodePort cho web service
├── haproxy/haproxy.cfg.tmpl      # template cấu hình HAProxy
└── README.md                     # file này
```
