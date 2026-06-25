# Tái tạo hệ thống Auto-scaling K8s (GRU + KEDA)

Bộ manifest YAML thuần để dựng lại toàn bộ stack theo thiết kế: web service (workload),
predictor (GRU), Prometheus, Pushgateway, Grafana, HAProxy, kube-state-metrics, KEDA.

Giao tiếp trong cluster dùng **service DNS nội bộ** (không phụ thuộc IP node) — bạn đổi
server sang IP mới chỉ ở các NodePort khi truy cập từ ngoài.

## Sơ đồ thành phần

```
Người dùng → HAProxy(:30080) → carserv-svc → carserv-deploy (1..10 pod)  [ns: carserv]
                                                     ▲ scale
predictor ──HTTP POST──► Pushgateway ──scrape 30s──► Prometheus ──query──► KEDA ──HPA──┘
   (GRU)                  (:30060)                    (:30090)
                                                         ▲
                       kube-state-metrics ──────────────┤  (đếm pod, container CPU qua cAdvisor)
                                  Grafana(:30030) ───────┘
```

## Cần điền trước khi apply

| File | Chỗ cần sửa |
|------|-------------|
| `05-carserv-webservice.yaml` | `<IMAGE>` → image web service thật + `containerPort` nếu khác 80 |
| `07-predictor.yaml` | `<PREDICTOR_IMAGE>` → image predictor (đã chứa sẵn `gru_cpu_model.keras`, `scaler.pkl`, `model_config.json` trong `/app`) |
| `04-grafana.yaml` | đổi `GF_SECURITY_ADMIN_PASSWORD` |

## Thứ tự triển khai

```bash
# 1) Cài KEDA operator TRƯỚC (chỉ làm 1 lần)
kubectl apply --server-side -f \
  https://github.com/kedacore/keda/releases/download/v2.14.0/keda-2.14.0.yaml
kubectl get pods -n keda            # đợi keda-operator Running

# 2) Apply toàn bộ stack theo thứ tự
kubectl apply -f 00-namespaces.yaml
kubectl apply -f 01-kube-state-metrics.yaml
kubectl apply -f 02-prometheus.yaml
kubectl apply -f 03-pushgateway.yaml
kubectl apply -f 04-grafana.yaml
kubectl apply -f 05-carserv-webservice.yaml   # sau khi điền <IMAGE>
kubectl apply -f 06-haproxy.yaml
kubectl apply -f 07-predictor.yaml            # sau khi điền <PREDICTOR_IMAGE>
kubectl apply -f 08-keda-scaledobject.yaml

# Hoặc apply cả thư mục (KEDA vẫn phải cài ở bước 1 trước):
# kubectl apply -f .
```

## Truy cập (thay <NODE_IP> bằng IP node mới của bạn)

| Dịch vụ | URL |
|---------|-----|
| Web (qua HAProxy) | http://<NODE_IP>:30080 |
| HAProxy stats | http://<NODE_IP>:30084 |
| Prometheus | http://<NODE_IP>:30090 |
| Pushgateway | http://<NODE_IP>:30060 |
| Grafana | http://<NODE_IP>:30030  (admin / admin123) |

## Kiểm tra hoạt động

```bash
kubectl get pods -n monitoring
kubectl get pods -n carserv
kubectl logs -n carserv deploy/predictor -f          # xem chu kỳ dự báo
kubectl get scaledobject,hpa -n carserv              # KEDA tạo HPA carserv-scaler
# Kiểm tra metric đã lên Prometheus:
#   mở http://<NODE_IP>:30090  → query: predicted_n_pods / predicted_pod_cpu
```

## Lưu ý quan trọng (chỉ có master + 1 worker)

- **Mặc định master bị taint** nên pod chỉ chạy trên 1 worker. Với MAX_PODS=10 + cả
  stack monitoring, 1 worker có thể không đủ tài nguyên. Nếu muốn dùng cả master làm
  chỗ chạy pod:
  ```bash
  kubectl taint nodes <ten-master-node> node-role.kubernetes.io/control-plane- 
  ```
- **Storage tạm**: Prometheus và Grafana đang dùng `emptyDir` → mất dữ liệu khi pod
  restart. Muốn giữ lại thì thay bằng PVC (cần StorageClass).
- **container_cpu_usage_seconds_total**: lấy từ cAdvisor qua kubelet. Nếu Prometheus
  báo target cadvisor `down`, kiểm tra kubelet cho phép `/metrics/cadvisor` và RBAC
  `nodes/proxy` (đã cấp trong `02-prometheus.yaml`).
- **TESTBED_MODE**: khi bắn tải giả bằng k6/testbed, đổi env `TESTBED_MODE="true"`
  trong `07-predictor.yaml` để predictor query `testbed_cpu_usage` thay vì cAdvisor.
- **KEDA so với predictor**: predictor chỉ *tính & đẩy* `predicted_n_pods`; việc
  *patch/scale* deployment do KEDA làm (đọc metric đó với threshold=1).
```
