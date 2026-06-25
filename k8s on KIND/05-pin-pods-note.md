# Ghim Pod đúng node theo Biểu đồ triển khai (nodeSelector)

Sau khi chạy `04-label-nodes.sh`, hai worker có nhãn:

| Node | Nhãn | Vai trò trong sơ đồ |
|------|------|---------------------|
| `k8s-worker1` | `node-role=management` | AI scaler (predictor), Prometheus, Pushgateway, Grafana, kube-state-metrics + web service |
| `k8s-worker2` | `node-role=workload` | Chỉ các Pod web service |

## Cách ghim: thêm `nodeSelector` vào phần `spec.template.spec` của Deployment

**Các Pod quản lý → Worker 1** (`07-predictor.yaml`, `02-prometheus.yaml`, `03-pushgateway.yaml`, `04-grafana.yaml`, `01-kube-state-metrics.yaml`):

```yaml
spec:
  template:
    spec:
      nodeSelector:
        node-role: management
      # ... containers giữ nguyên
```

**Web service** (`05-carserv-webservice.yaml`): sơ đồ cho thấy web chạy ở CẢ worker1 và worker2.
Có 2 lựa chọn:

1. **Để Kubernetes tự rải** (khuyến nghị) — không đặt `nodeSelector`, thêm topology spread
   để KEDA scale ra thì pod trải đều 2 worker:

   ```yaml
   spec:
     template:
       spec:
         topologySpreadConstraints:
           - maxSkew: 1
             topologyKey: kubernetes.io/hostname
             whenUnsatisfiable: ScheduleAnyway
             labelSelector:
               matchLabels:
                 app: carserv
   ```

2. **Ép web service chỉ chạy ở workload node** (nếu muốn worker1 chỉ lo quản lý):

   ```yaml
   spec:
     template:
       spec:
         nodeSelector:
           node-role: workload
   ```

## Áp nhanh bằng `kubectl patch` (không cần sửa file)

```bash
# Ghim predictor + monitoring stack vào worker1 (management)
for d in predictor prometheus pushgateway grafana kube-state-metrics; do
  ns=carserv; [ "$d" = "predictor" ] || ns=monitoring
  kubectl -n "$ns" patch deploy "$d" --type merge \
    -p '{"spec":{"template":{"spec":{"nodeSelector":{"node-role":"management"}}}}}' 2>/dev/null \
    && echo "pinned $d -> management"
done
```

> Lưu ý namespace thực tế tùy theo manifest của bạn (`00-namespaces.yaml`). Chỉnh `ns` cho khớp.
> Master node mặc định bị taint `node-role.kubernetes.io/control-plane:NoSchedule`
> nên không pod ứng dụng nào chạy ở đó — đúng như sơ đồ (master chỉ là Control Plane).
