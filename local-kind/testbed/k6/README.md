# k6 bắn tải tái hiện trace CPU của data_host (ánh xạ RPS → CPU)

Mục tiêu: thay tín hiệu testbed tổng hợp bằng **tải HTTP thật từ k6**, được định hình để
**CPU sinh ra giống trace data_host** (test set). Cần: app đốt CPU + hiệu chỉnh RPS→CPU + sinh kịch bản.

> ⚠️ Vòng kín vs vòng hở: khi BẬT autoscaling, hệ thống điều tiết CPU/pod về mục tiêu →
> CPU mỗi pod KHÔNG bám trace, mà SỐ POD bám tải. Muốn thấy "CPU bám trace" rõ thì đo ở
> **1 pod cố định (vòng hở)**. Vì vậy quy trình có 2 lần chạy khác mục đích (Bước 4A/4B).

---

## Bước 0 — Build & triển khai app đốt CPU (thay carserv tĩnh)

```bash
cd "/mnt/d/DATN/Tổng hợp/Manifest"
DOCKER_BUILDKIT=0 docker build -f local-kind/testbed/k6/Dockerfile -t datn/cpuapp:v1 local-kind/testbed/k6
kind load docker-image datn/cpuapp:v1 --name datn
kubectl -n carserv set image deploy/carserv-deploy carserv=datn/cpuapp:v1
kubectl -n carserv set env deploy/carserv-deploy WORK_ITERS=150000   # chỉnh độ "nặng" mỗi request
```

Chuyển predictor sang đọc CPU THẬT:
```bash
kubectl -n carserv set env deploy/predictor TESTBED_MODE=false INTERVAL_SEC=300
```
Và dừng injector testbed (giờ dùng k6 thật):
```bash
pkill -f inject_testbed
```

---

## Bước 1 — Cố định 1 pod để hiệu chỉnh (vòng hở)

```bash
kubectl annotate scaledobject carserv-scaler -n carserv autoscaling.keda.sh/paused-replicas="1" --overwrite
kubectl -n carserv scale deploy/carserv-deploy --replicas=1
kubectl get pods -n carserv | grep carserv-deploy   # đúng 1 pod
```

> 💡 **CPU limit chặn dải đo:** deploy mặc định đặt `limits.cpu=250m` → CPU đo (`rate*100`, theo % của 1 core)
> KHÔNG vượt ~25% dù tăng RPS (bị throttle, mapping mất tuyến tính). Muốn dải CPU rộng (0–100%) cho hình
> "CPU bám trace", nâng limit cho pod hiệu chỉnh — nhớ giữ **nhất quán** giữa lúc hiệu chỉnh và lúc demo:
> ```bash
> kubectl -n carserv set resources deploy/carserv-deploy -c carserv \
>   --requests=cpu=200m,memory=128Mi --limits=cpu=1000m,memory=512Mi
> kubectl -n carserv rollout status deploy/carserv-deploy
> ```

## Bước 2 — Đo CPU ở vài mức RPS

Với mỗi mức, chạy k6 **≥3 phút** rồi đọc CPU ở cuối. Lặp cho RATE = 10, 20, 40, 80...

```bash
# Bắn tải mức RATE (terminal 1) — DURATION 3m để phủ trọn cửa sổ rate[2m] khi đọc CPU
RATE=20 DURATION=3m BASE_URL=http://localhost:30080 k6 run local-kind/testbed/k6/calibrate.js
```
```bash
# Đọc CPU% tương ứng (terminal 2, chạy ở ~cuối, khi CPU đã ổn định)
bash local-kind/testbed/k6/cpu.sh        # in: CPU% = <số>
```

> ⚠️ KHÔNG dùng query cũ `...container!=""...[1m]...`. Trên cụm KIND này metric cadvisor có CẢ series mức pod
> (không nhãn `container`) LẪN series `container="carserv"`; lọc sai → rỗng hoặc đếm trùng. Thêm nữa `rate[1m]`
> hay rỗng do Prometheus scrape thưa. Script `cpu.sh` đã lọc đúng `container="carserv"` + cửa sổ `[2m]` (chỉnh:
> `WIN=3m bash local-kind/testbed/k6/cpu.sh`).

Ghi lại thành bảng, ví dụ:
| RPS | CPU% đo được |
|-----|------|
| 10  | 10.5 |
| 20  | 19.8 |
| 40  | 38.0 |
| 80  | 73.0 |

## Bước 3 — Tính hệ số ánh xạ CPU = a·RPS + b

Khớp tuyến tính (2 điểm là đủ, nhiều điểm thì chính xác hơn). Ví dụ dùng 2 điểm (20→19.8) và (80→73.0):
```
a = (73.0 - 19.8) / (80 - 20) = 0.887
b = 19.8 - 0.887*20 = 2.06
```
→ `a≈0.89`, `b≈2.0`. (Nếu có 4-5 điểm, vẽ scatter hoặc dùng numpy.polyfit để fit đẹp hơn.)

## Bước 4 — Sinh kịch bản k6 từ trace test set

```bash
python3 local-kind/testbed/k6/gen_k6_from_trace.py \
  --csv "/mnt/d/DATN/Tổng hợp/Train mô hình/data_host_5m_filtered.csv" \
  --col host_cpu_usage --start-frac 0.90 \
  --a 0.89 --b 2.0 --seconds-per-point 30 \
  --out local-kind/testbed/k6/load_from_trace.js
```
(`--start-frac 0.90` = chỉ dùng test set; `--seconds-per-point 30` = nén mỗi điểm 5' thành 30s.)

## Bước 4A — Chạy VÒNG HỞ: xem CPU bám trace + GRU dự báo (1 pod)

Giữ nguyên 1 pod (đã pause KEDA ở Bước 1), chạy:
```bash
BASE_URL=http://localhost:30080 k6 run local-kind/testbed/k6/load_from_trace.js
```
Trên Grafana: CPU thật (`...container_cpu_usage...`) sẽ **bám theo hình trace data_host**, và
`predicted_pod_cpu` của GRU bám theo CPU thật → đây là hình "dự báo trên tải k6 thật".

## Bước 4B — Chạy VÒNG KÍN: xem autoscaling phản ứng

Bật lại KEDA:
```bash
kubectl annotate scaledobject carserv-scaler -n carserv autoscaling.keda.sh/paused-replicas- 
```
Chạy lại `load_from_trace.js`. Giờ khi tải lên, GRU dự báo → KEDA **scale pod**; CPU mỗi pod
được giữ gần mục tiêu, còn **số pod bám theo tải** → hình "auto-scaling theo tải k6 thật".

---

## Khôi phục về testbed (nếu muốn quay lại)

```bash
kubectl -n carserv set image deploy/carserv-deploy carserv=<IMAGE_carserv_cu>   # hoặc app tĩnh ban đầu
kubectl -n carserv set env deploy/predictor TESTBED_MODE=true INTERVAL_SEC=300
nohup python3 local-kind/testbed/inject_testbed.py replay --start-frac 0.90 --interval 300 --loop > /tmp/injector.log 2>&1 &
```

## Ghi vào báo cáo

- **k6** là công cụ sinh tải HTTP thật; tải được định hình bằng ánh xạ tuyến tính `CPU=a·RPS+b`
  (hiệu chỉnh thực nghiệm) để **tái tạo cường độ CPU theo trace tải thực** (test set).
- Hình 4A: CPU thật do k6 tạo bám theo trace + GRU dự báo (vòng hở, pod cố định).
- Hình 4B: số pod tự co giãn theo tải k6 (vòng kín) — minh hoạ predictive auto-scaling.
- Nêu rõ giới hạn: ánh xạ RPS→CPU tuyến tính gần đúng; CPU container khác CPU host gốc về tỉ lệ.

---

## Khắc phục sự cố (đã gặp khi chạy trên Windows + WSL2 + Docker Desktop)

- **`kubectl` báo `connection reset by peer` / `EOF` tới `https://127.0.0.1:<port>`** dù `docker ps` thấy node "Up":
  forwarder loopback của Docker Desktop bị kẹt (thường sau khi container restart hoặc sau cú `kind load`).
  *Fix:* PowerShell Windows chạy `wsl --shutdown` → chuột phải cá voi 🐳 khay hệ thống → **Quit Docker Desktop**
  → mở lại, đợi 🟢 *Engine running* → `kind export kubeconfig --name datn` → `kubectl get nodes`.
  (Chạy lại script bên trong WSL là vô ích.) Dự phòng gấp, bỏ qua forwarder:
  `docker exec -i datn-control-plane kubectl --kubeconfig /etc/kubernetes/admin.conf <args>`.
  KHÔNG repoint kubeconfig sang IP container `172.18.0.x:6443` — WSL không route tới được.

- **`kind load docker-image` rồi kubectl reset:** cú load làm bão hòa I/O daemon → reset tạm thời. Hoặc nạp
  thẳng vào containerd từng node để nhẹ hơn: `docker save datn/cpuapp:v1 | docker exec -i <node> ctr -n k8s.io images import -`.

- **k6 báo `cannot preserve mount namespace ... / unexpected eof from helper process`:** k6 cài qua **snap**,
  snap không chạy trên WSL2. *Fix:* `sudo snap remove k6` rồi cài binary tĩnh từ GitHub release vào `/usr/local/bin/k6`.

- **Query CPU trả `IndexError`/`EMPTY`:** xem cảnh báo ở Bước 2 — dùng `cpu.sh` (lọc `container="carserv"`, cửa sổ `[2m]`).

- **Pod `carserv-deploy` RESTARTS cao:** kiểm `kubectl -n carserv describe pod -l app=carserv | grep -A6 'Last State'`.
  `OOMKilled` → tăng `--limits=memory`. Log có `ConnectionResetError` khi bắn k6 là **vô hại** (k6 đóng kết nối,
  `ThreadingHTTPServer` không chết).
