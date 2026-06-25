# Chạy hệ thống Auto-scaling (GRU + KEDA) trên cụm kind 3 node — KHÔNG cần OpenStack

Bộ file này thay thế hạ tầng **4 VM OpenStack** bằng cụm **kind** 3 node chạy trên 1 máy.
Toàn bộ kiến trúc K8s (web service, predictor GRU, Prometheus, Pushgateway, Grafana,
kube-state-metrics, HAProxy, KEDA) giữ **nguyên không đổi** — chỉ đổi lớp hạ tầng bên dưới.

> **Vì sao mô phỏng được:** đề tài scale **POD** (KEDA → HPA, 1→10 pod) trên các node có
> sẵn, *không* scale NODE (không dùng Cluster Autoscaler) → không cần IaaS tạo VM động.

---

## 0. Làm Ở ĐÂU — môi trường chạy

Máy Windows 11 + 32GB RAM. Cách gọn nhất:

1. **Cài Docker Desktop** (bản Windows) → bật **WSL2 backend**
   (Settings → General → *Use the WSL 2 based engine*; và Settings → Resources → WSL Integration → bật cho Ubuntu).
2. **Cài WSL2 Ubuntu** (nếu chưa có): mở PowerShell (Admin) → `wsl --install -d Ubuntu` → khởi động lại.
3. **Mọi lệnh bên dưới chạy trong terminal Ubuntu (WSL2)**, không phải PowerShell.
   Thư mục dự án truy cập từ WSL tại: `/mnt/d/DATN/Tổng hợp/Manifest`.

> Giới hạn RAM cho WSL2 (khuyến nghị): tạo file `C:\Users\PC\.wslconfig`:
> ```ini
> [wsl2]
> memory=16GB
> processors=6
> ```
> rồi `wsl --shutdown` trong PowerShell để áp dụng. 16GB là đủ cho 3 node + full stack.

### Cài công cụ trong Ubuntu (WSL2)

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.23.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# kiểm tra docker đã thông từ WSL
docker version          # phải thấy cả Client và Server (Docker Desktop)
kind version; kubectl version --client
```

*(Tùy chọn)* k6 để bắn tải giả:
```bash
sudo gpg -k && sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install -y k6
```

---

## 1. Các bước chạy (theo thứ tự)

```bash
cd "/mnt/d/DATN/Tổng hợp/Manifest"

# (1) Dựng cụm 3 node + gắn nhãn + cài KEDA
bash local-kind/01-create-cluster.sh

# (2) Build image predictor (GRU) + nạp vào kind
bash local-kind/02-build-load-images.sh
```

**(3) Điền image vào manifest** (chỉ làm 1 lần):
- `k8s/07-predictor.yaml`: thay `<PREDICTOR_IMAGE>` → `datn/predictor:v1`,
  và thêm dòng `imagePullPolicy: IfNotPresent` ngay dưới `image:` (vì image là local trong kind).
- `k8s/05-carserv-webservice.yaml`: thay `<IMAGE>` → image web service của bạn
  (hoặc `registry.k8s.io/hpa-example` nếu chỉ cần workload demo — xem chú thích trong `02-build-load-images.sh`),
  cũng thêm `imagePullPolicy: IfNotPresent` nếu là image local đã `kind load`.

```bash
# (4) Apply toàn bộ stack + ghim pod đúng node
bash local-kind/03-deploy.sh
```

---

## 2. Truy cập (mở trình duyệt trên Windows)

| Dịch vụ | URL |
|---------|-----|
| Web (qua HAProxy) | http://localhost:30080 |
| HAProxy stats | http://localhost:30084 |
| Prometheus | http://localhost:30090 |
| Pushgateway | http://localhost:30060 |
| Grafana | http://localhost:30030 |

(Nhờ `extraPortMappings` trong `kind-cluster.yaml`, NodePort của cụm map thẳng ra `localhost`.)

---

## 3. Kiểm tra auto-scaling hoạt động

```bash
kubectl get nodes -o wide                       # 3 node Ready, role management/workload
kubectl get pods -A -o wide                      # pod nằm đúng node đã ghim
kubectl get scaledobject,hpa -n carserv          # KEDA tạo HPA carserv-scaler
kubectl logs -n carserv deploy/predictor -f      # xem chu kỳ dự báo GRU

# Bắn tải giả để thấy số pod tăng (1 -> ... -> 10):
#   - đổi TESTBED_MODE="true" trong k8s/07-predictor.yaml rồi apply lại, hoặc
#   - dùng k6 nhắm vào http://localhost:30080
kubectl get pods -n carserv -w                    # quan sát pod carserv scale
```

---

## 4. Dọn dẹp / làm lại

```bash
kind delete cluster --name datn      # xóa sạch cụm
```

---

## 5. Ghi vào báo cáo (mục 4.8 "Môi trường thực nghiệm")

Trình bày trung thực: hạ tầng thử nghiệm dùng **cụm Kubernetes 3 node (1 control-plane +
2 worker) dựng bằng kind trên một máy**, thay cho 4 VM OpenStack trong thiết kế gốc. Topology,
phân vai node (management/workload), và toàn bộ thành phần phần mềm giữ nguyên; khác biệt chỉ
nằm ở lớp ảo hóa (container thay vì VM). Đóng góp chính của đề tài — dự báo tải bằng GRU và
predictive scaling qua KEDA — không phụ thuộc lớp hạ tầng này.

## 6. Lỗi thường gặp

| Triệu chứng | Cách xử lý |
|-------------|-----------|
| `ErrImageNeverPull` / `ImagePullBackOff` | Chưa `kind load` image, hoặc thiếu `imagePullPolicy: IfNotPresent` |
| `docker` không chạy trong WSL | Bật WSL Integration trong Docker Desktop; mở lại terminal |
| Pod `Pending` mãi | nodeSelector trỏ nhãn không tồn tại → `kubectl get nodes --show-labels` kiểm tra `node-role` |
| Không vào được `localhost:30080` | Pod web chưa Ready, hoặc HAProxy backend DOWN → xem `http://localhost:30084` |
| Prometheus target cadvisor `down` | RBAC `nodes/proxy` (đã có trong 02-prometheus.yaml); trên kind cAdvisor qua kubelet vẫn hoạt động |
