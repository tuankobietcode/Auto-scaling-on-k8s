# CHEAT-SHEET LỆNH DEMO (khi báo cáo)

Tất cả chạy trong **WSL2 Ubuntu**. Trừ khi ghi khác, đứng ở:
```bash
cd "/mnt/d/DATN/Tổng hợp/Manifest"
```

> ⚠️ Demo live không nên bắt đầu từ con số 0: với nhịp 5 phút, cửa sổ GRU cần ~2h mới đầy.
> **Khởi động hệ thống + injector trước buổi báo cáo ~1–2 giờ** để Grafana đã có biểu đồ đẹp.
> Khi trình bày chỉ mở các cửa sổ quan sát. (Hoặc dùng "demo nhanh" ở mục E.)

---

## A. Kiểm tra cụm còn sống không (sau khi bật lại máy)

```bash
kind get clusters                 # phải thấy: datn
kubectl get nodes                 # 3 node Ready
kubectl get pods -A | grep -vE 'Running|Completed'   # rỗng = mọi pod đều OK
```
Nếu node chưa Ready (Docker vừa khởi động lại), đợi 1–2 phút rồi kiểm tra lại.

## B. Nếu cụm CHƯA có (dựng lại từ đầu)

```bash
bash local-kind/01-create-cluster.sh        # dựng 3 node + nhãn + KEDA
bash local-kind/02-build-load-images.sh     # build + nạp image predictor
bash local-kind/03-deploy.sh                # apply toàn bộ stack + ghim pod
```

## C. Kiểm tra trước khi diễn (BẮT BUỘC chạy trước buổi báo cáo)

```bash
kubectl get pods -n carserv -o wide          # carserv-deploy + predictor Running
kubectl get pods -n monitoring               # prometheus/grafana/pushgateway/haproxy/ksm Running
kubectl get scaledobject,hpa -n carserv      # ScaledObject READY=True, có keda-hpa-...
```
Bật chế độ testbed (nếu chưa):
```bash
kubectl -n carserv set env deploy/predictor TESTBED_MODE=true INTERVAL_SEC=300
```

---

## D. CHẠY DEMO — mở 3–4 terminal + trình duyệt

**Terminal 1 — Bơm tín hiệu CPU (nguồn vào):**
```bash
# Trung thực với dữ liệu train (mỗi điểm 5 phút):
python3 "local-kind/testbed/inject_testbed.py" replay --interval 300 --loop
# HOẶC sóng cho thấy scaling rõ:
# python3 "local-kind/testbed/inject_testbed.py" wave --low 5 --high 130 --period 7200 --interval 300
```

**Terminal 2 — Log dự báo (bộ não):**
```bash
kubectl logs -n carserv deploy/predictor -f
```

**Terminal 3 — Pod scale theo thời gian thực (kết quả):**
```bash
watch -n 5 'echo "=== POD carserv-deploy ==="; kubectl get pods -n carserv | grep carserv-deploy; echo; kubectl get hpa -n carserv'
```

**Trình duyệt — Grafana (trực quan nhất):**
```
http://localhost:30030     (admin / admin123)  → Dashboards → DATN → DATN Auto-scaling
```
Các URL khác: Prometheus `:30090` · Pushgateway `:30060` · Web `:30080` · HAProxy stats `:30084`

---

## E. DEMO NHANH (nếu cần show scaling live trong vài phút)

Tạm nén thời gian: đổi `resample_min` 5→1, build lại, dùng sóng chu kỳ ngắn.
```bash
# 1) sửa Manifest/model/model_config.json: "resample_min": 1   (sửa tay hoặc lệnh sed)
sed -i 's/"resample_min": 5/"resample_min": 1/' model/model_config.json
docker build -f predictor/Dockerfile -t datn/predictor:demo .
kind load docker-image datn/predictor:demo --name datn
kubectl -n carserv set image deploy/predictor predictor=datn/predictor:demo
kubectl -n carserv set env deploy/predictor TESTBED_MODE=true INTERVAL_SEC=60
# 2) bơm sóng nhanh:
python3 "local-kind/testbed/inject_testbed.py" wave --low 5 --high 130 --period 1800 --interval 30
```
Sau ~25–30 phút có biểu đồ scaling đầy đủ. (Nhớ ghi rõ trong báo cáo: đây là demo nén thời gian.)

---

## F. Reset giữa các lần chạy

```bash
# Xoá metric testbed cũ trong Pushgateway
curl -X DELETE http://localhost:30060/metrics/job/testbed/namespace/carserv
# Đưa số replica về 1 (KEDA sẽ tự điều chỉnh lại theo tín hiệu)
kubectl -n carserv scale deploy/carserv-deploy --replicas=1
```

## G. Tắt / dọn dẹp

```bash
# Trả predictor về chế độ thường
kubectl -n carserv set env deploy/predictor TESTBED_MODE=false INTERVAL_SEC=300
# Xoá hẳn cụm (làm lại từ đầu khi cần)
kind delete cluster --name datn
```

---

## H. Lệnh "cứu hộ" khi sự cố lúc demo

```bash
kubectl get pods -A | grep -vE 'Running|Completed'        # pod nào hỏng?
kubectl describe pod -n carserv <ten-pod>                  # vì sao Pending/CrashLoop?
kubectl logs -n carserv deploy/predictor --previous --tail=40   # log lần crash trước
kubectl rollout restart deploy/<ten> -n <namespace>        # khởi động lại 1 thành phần
kubectl get events -n carserv --sort-by=.lastTimestamp | tail -20
```
