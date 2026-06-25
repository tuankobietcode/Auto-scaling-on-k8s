# Demo Auto-scaling theo chu kỳ + xuất tín hiệu cho báo cáo

Vì `carserv` là **app tĩnh** (không sinh CPU khi bị bắn tải), ta điều khiển scaling bằng
**tín hiệu CPU mô phỏng** bơm vào Pushgateway (`testbed_cpu_usage`), đúng cơ chế `TESTBED_MODE`
mà thiết kế đã có. k6 bắn tải HTTP song song chỉ để có lưu lượng thật + biểu đồ request.

```
inject_testbed.py ──push──► Pushgateway ──scrape──► Prometheus ──► predictor(GRU) ──► predicted_n_pods ──► KEDA ──► scale carserv
k6 (loadtest.js) ──HTTP──► HAProxy(:30080) ──► carserv         (chỉ tạo traffic minh hoạ)
```

---

## 1. Chuẩn bị predictor cho chế độ testbed (một lần)

`resample_min` giữ = 5 (đồng bộ với training — cửa sổ GRU = 24 × 5 = 120 phút). Build lại
image để áp model_config mới nhất. Chạy từ `Manifest/`:

```bash
cd "/mnt/d/DATN/Tổng hợp/Manifest"
docker build -f predictor/Dockerfile -t datn/predictor:v5 .
kind load docker-image datn/predictor:v5 --name datn
kubectl -n carserv set image deploy/predictor predictor=datn/predictor:v5
```

Bật TESTBED_MODE, giữ chu kỳ dự báo 5 phút (không cần build lại — chỉ là biến môi trường):

```bash
kubectl -n carserv set env deploy/predictor TESTBED_MODE=true INTERVAL_SEC=300
kubectl get pods -n carserv -w        # đợi predictor Running lại, rồi Ctrl+C
```

Xác nhận log đã chuyển sang query testbed:
```bash
kubectl logs -n carserv deploy/predictor --tail=20
# Phải thấy:  Query : testbed_cpu_usage{job="testbed",namespace="carserv"}
```

---

## 2. Bơm tín hiệu CPU (chọn 1 chế độ)

Mở **một terminal WSL riêng**, để chạy nền suốt buổi demo:

```bash
cd "/mnt/d/DATN/Tổng hợp/Manifest/local-kind/testbed"

# (A) PHÁT LẠI dữ liệu thật, mỗi điểm 5 phút — đồng bộ với training, trung thực nhất
python3 inject_testbed.py replay --interval 300 --loop

# (B) SÓNG tổng hợp 5%..130%, chu kỳ 2h, mỗi 5 phút — cho thấy scaling đầy đủ 1↔10 pod
python3 inject_testbed.py wave --low 5 --high 130 --period 7200 --interval 300
```

> Cửa sổ GRU = 24 điểm × 5 phút = **120 phút (2 giờ)** để đầy hoàn toàn (giống một cửa sổ
> lúc training). Những phút đầu predictor vẫn dự báo (đệm bằng giá trị đầu), nhưng biểu đồ
> đầy đủ & đẹp nhất sau ~2 giờ chạy liên tục. Nên để injector chạy nền lâu rồi mới chụp.

## 3. (song song) Bắn tải HTTP bằng k6 — tùy chọn, để có traffic thật

Terminal WSL khác:
```bash
cd "/mnt/d/DATN/Tổng hợp/Manifest/local-kind/testbed"
BASE_URL=http://localhost:30080 k6 run loadtest.js
```
Xem request phân phối tới pod ở trang HAProxy stats: http://localhost:30084

## 4. Quan sát scaling

```bash
watch -n 2 'kubectl get pods -n carserv -o wide | grep carserv-deploy | wc -l'   # đếm pod theo thời gian
kubectl get hpa -n carserv -w                                                    # REPLICAS thay đổi
kubectl logs -n carserv deploy/predictor -f                                      # cpu_pred -> n_pods
```

---

## 5. Dùng Grafana xuất tín hiệu cho báo cáo

Mở **http://localhost:30030** (admin / admin123). Datasource Prometheus đã có sẵn.

### Tạo dashboard
`Dashboards → New → New dashboard → Add visualization → chọn datasource Prometheus`.
Thêm các panel sau (mỗi panel một query PromQL, kiểu **Time series**):

| Panel | Query PromQL | Đơn vị |
|-------|--------------|--------|
| CPU mô phỏng (đầu vào) | `testbed_cpu_usage{namespace="carserv"}` | percent (0-100) |
| CPU dự báo (GRU) | `predicted_pod_cpu{namespace="carserv"}` | percent |
| Số pod khuyến nghị | `predicted_n_pods{namespace="carserv"}` | short |
| Số pod thực tế đang chạy | `count(kube_pod_status_phase{namespace="carserv",phase="Running"})` | short |
| (gộp so sánh) | thêm cả 2 query `predicted_n_pods{namespace="carserv"}` và `count(kube_pod_status_phase{namespace="carserv",phase="Running"})` trong **một** panel | short |

> Panel "gộp so sánh" là hình **đắt giá nhất** cho mục 4.9: đặt cạnh nhau *số pod dự báo*
> và *số pod thực tế* để thấy KEDA bám theo khuyến nghị của GRU. Có thể thêm
> `testbed_cpu_usage` (trục Y phụ) để thấy nhân-quả: CPU tăng → dự báo tăng → pod tăng.

### Xuất ra báo cáo
- **Ảnh PNG**: panel → menu (⋮) → **Share → ... → Render image** (hoặc chụp màn hình). Đặt
  khoảng thời gian (góc phải trên) = "Last 1 hour" để bao trọn buổi demo.
- **Số liệu thô (đẹp nhất để vẽ lại bằng Python/matplotlib)**: panel → **Inspect → Data →
  Download CSV**. Dùng CSV này vẽ hình chất lượng in ấn cho phần phụ lục.
- **Lưu cấu hình dashboard**: Dashboard settings → **Save dashboard**; để tái lập được, export
  JSON (Share → Export → Save to file) và đính kèm vào phụ lục "Cấu hình giám sát".

---

## 6. Trả hệ thống về chế độ thường (sau demo)

```bash
kubectl -n carserv set env deploy/predictor TESTBED_MODE=false INTERVAL_SEC=300
```
(Và xóa metric testbed cũ trong Pushgateway nếu muốn: `curl -X DELETE http://localhost:30060/metrics/job/testbed/namespace/carserv`)

## 7. Gợi ý trình bày trong báo cáo (mục 4.9)

1. **Hình 1 — Tín hiệu vào/ra**: testbed_cpu_usage vs predicted_pod_cpu → chứng minh GRU bám tải.
2. **Hình 2 — Khả năng auto-scaling**: predicted_n_pods vs số pod thực tế → KEDA thực thi đúng.
3. **Hình 3 — So với HPA truyền thống**: chạy lại kịch bản wave nhưng dùng HPA CPU mặc định
   (không predictor) và so độ trễ phản ứng — đây là luận điểm chính của đề tài (predictive
   phản ứng sớm hơn reactive). Mình có thể giúp bạn dựng HPA đối chứng khi cần.
