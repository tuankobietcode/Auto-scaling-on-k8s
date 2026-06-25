# predictor/predictor.py
import json, pickle, time, logging, math, os
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timezone

# TensorFlow log bớt ồn trước khi import
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
from tensorflow import keras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROMETHEUS_URL   = os.getenv("PROMETHEUS_URL",   "http://192.168.180.43:30090")
PUSHGATEWAY_URL  = os.getenv("PUSHGATEWAY_URL",  "http://192.168.180.43:30060")
MODEL_PATH       = "/app/gru_cpu_model.keras"
SCALER_PATH      = "/app/scaler.pkl"
CONFIG_PATH      = "/app/model_config.json"
NAMESPACE        = os.getenv("NAMESPACE",         "carserv")
TARGET_DEPLOYMENT= os.getenv("TARGET_DEPLOYMENT", "carserv-deploy")
POD_CAPACITY     = float(os.getenv("POD_CAPACITY",    "25"))  # CPU cấp cho 1 pod (=limits.cpu, %-core: 250m->25) -> mẫu số tính %util
SCALE_UP_UTIL    = float(os.getenv("SCALE_UP_UTIL",   "80"))  # %util/pod dự báo > ngưỡng này -> scale up
SCALE_DOWN_UTIL  = float(os.getenv("SCALE_DOWN_UTIL", "30"))  # < ngưỡng này -> scale down
TARGET_UTIL      = float(os.getenv("TARGET_UTIL",     "65"))  # %util/pod mục tiêu khi scale (giữa 30..80)
BUFFER           = float(os.getenv("BUFFER",          "1.2")) # biên an toàn dưới SLA: cấp dư pod (bù model dự báo hụt ≤20%)
MIN_PODS         = int(os.getenv("MIN_PODS",       "1"))
MAX_PODS         = int(os.getenv("MAX_PODS",       "10"))
INTERVAL_SEC     = int(os.getenv("INTERVAL_SEC",   "300"))
TESTBED_MODE     = os.getenv("TESTBED_MODE", "false").lower() == "true"

# Tự động chọn query dựa theo mode
PROMETHEUS_QUERY = (
    f'testbed_cpu_usage{{job="testbed",namespace="{NAMESPACE}"}}'
    if TESTBED_MODE else
    # sum (KHÔNG avg): tổng CPU mọi pod ≈ mức trace gốc bất kể số pod. avg sẽ bị chia N
    # -> tụt dưới dải model được train -> dự báo "đơ". sum giữ đầu vào đúng phân phối train.
    f'sum(rate(container_cpu_usage_seconds_total{{namespace="{NAMESPACE}",'
    f'pod=~"{TARGET_DEPLOYMENT}-.*",container="carserv"}}[5m])) * 100'

)

# Chỉ đếm pod của deployment mục tiêu (carserv-deploy), KHÔNG tính pod predictor
# hay pod khác trong cùng namespace -> tránh đếm dư.
POD_COUNT_QUERIES = [
    (f'count(kube_pod_status_phase{{namespace="{NAMESPACE}",pod=~"{TARGET_DEPLOYMENT}-.*",phase="Running"}})', "kube_pod_status_phase"),
    (f'count(kube_pod_info{{namespace="{NAMESPACE}",pod=~"{TARGET_DEPLOYMENT}-.*"}})', "kube_pod_info"),
    (f'count(count by(pod)(container_cpu_usage_seconds_total{{namespace="{NAMESPACE}",pod=~"{TARGET_DEPLOYMENT}-.*"}}))' , "cpu-metric"),
]

def load_artifacts():
    with open(CONFIG_PATH) as f: config = json.load(f)
    with open(SCALER_PATH, "rb") as f: scaler = pickle.load(f)
    model = keras.models.load_model(MODEL_PATH)
    n_feat = getattr(scaler, "n_features_in_", 1)
    if n_feat != 1:
        log.warning(f"Scaler có {n_feat} features nhưng predictor chạy univariate (1 feature CPU). "
                    f"Kiểm tra lại scaler.pkl nếu kết quả bất thường.")
    log.info(f"Model loaded | look_back={config['look_back']} bước "
             f"({config['look_back']*config['resample_min']} phút) | "
             f"input_size={config.get('input_size', 1)}")
    return model, scaler, config

def fetch_cpu_history(look_back, resample_min):
    end   = int(datetime.now(timezone.utc).timestamp())
    start = end - look_back * resample_min * 60
    resp  = requests.get(f"{PROMETHEUS_URL}/api/v1/query_range",
                         params={"query": PROMETHEUS_QUERY, "start": start,
                                 "end": end, "step": f"{resample_min}m"}, timeout=10)
    resp.raise_for_status()
    results = resp.json()["data"]["result"]
    if not results:
        raise ValueError(f"Không có data! Query: {PROMETHEUS_QUERY}")
    values = results[0]["values"]
    series = pd.Series([float(v[1]) for v in values],
                       index=pd.to_datetime([v[0] for v in values], unit="s"))
    return series.rolling(3, center=True, min_periods=1).mean().ffill().bfill()

def fetch_current_pods():
    for query, source in POD_COUNT_QUERIES:
        try:
            resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                                params={"query": query}, timeout=8)
            results = resp.json().get("data", {}).get("result", [])
            if results:
                count = int(float(results[0]["value"][1]))
                log.info(f"Pod hiện tại: {count} (source={source})")
                return count
        except: pass
    return 0

def build_tensor(series, scaler, look_back):
    # Univariate: chỉ dùng chuỗi CPU, shape (1, look_back, 1)
    values = series.values.astype("float32")
    if len(values) < look_back:
        pad = np.full(look_back - len(values), values[0], dtype="float32")
        values = np.concatenate([pad, values])
    window = values[-look_back:].reshape(-1, 1)
    scaled = scaler.transform(window)
    return scaled.reshape(1, look_back, 1).astype("float32")

def predict_cpu(model, tensor, scaler):
    out = model.predict(tensor, verbose=0)
    pred_scaled = float(np.asarray(out).reshape(-1)[0])
    pred = float(scaler.inverse_transform([[pred_scaled]])[0, 0])
    return float(np.clip(pred, 0, 100))

# Scale theo NGƯỠNG %util MỖI POD (hysteresis). Tín hiệu = TỔNG CPU dự báo (ngoại sinh, dự báo được);
# quyết định theo %util mỗi pod để vừa tận dụng tài nguyên vừa chống flapping:
#   util = (tổng_dự_báo / số_pod) / POD_CAPACITY × 100      (%so với hạn mức 1 pod)
#     util > SCALE_UP_UTIL   -> thêm pod
#     util < SCALE_DOWN_UTIL -> bớt pod
#     trong [down, up]       -> giữ nguyên
#   Khi scale: n = ceil(cur × util × BUFFER / TARGET_UTIL) -> kéo util về ~TARGET_UTIL,
#   nhân BUFFER để cấp dư pod cho an toàn SLA (model có thể dự báo hụt tới ~20%).
def calc_n_pods(predicted_total_cpu, current_pods):
    cur  = max(1, current_pods)
    util = (predicted_total_cpu / cur) / POD_CAPACITY * 100
    if util > SCALE_UP_UTIL or util < SCALE_DOWN_UTIL:
        n = math.ceil(cur * util * BUFFER / TARGET_UTIL)
    else:
        n = cur
    return max(MIN_PODS, min(MAX_PODS, n))

def push_to_gateway(predicted_cpu, n_pods, current_pods, util_pod):
    payload = "\n".join([
        "# HELP predicted_total_cpu Predicted TOTAL CPU across pods (% of one core)",
        "# TYPE predicted_total_cpu gauge",
        f"predicted_total_cpu {predicted_cpu:.4f}",
        "# HELP predicted_pod_util Predicted CPU utilization per pod (percent of pod limit) - scaling decision variable",
        "# TYPE predicted_pod_util gauge",
        f"predicted_pod_util {util_pod:.4f}",
        "# HELP predicted_n_pods Recommended number of pods",
        "# TYPE predicted_n_pods gauge",
        f"predicted_n_pods {n_pods}",
        "# HELP current_n_pods Current running pods",
        "# TYPE current_n_pods gauge",
        f"current_n_pods {current_pods}",
        "# HELP scale_up_threshold Scale-up util threshold (%)",
        "# TYPE scale_up_threshold gauge",
        f"scale_up_threshold {SCALE_UP_UTIL}",
        "# HELP scale_down_threshold Scale-down util threshold (%)",
        "# TYPE scale_down_threshold gauge",
        f"scale_down_threshold {SCALE_DOWN_UTIL}",
        "",
    ])
    resp = requests.post(
        f"{PUSHGATEWAY_URL}/metrics/job/predictor/namespace/{NAMESPACE}",
        data=payload.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        timeout=5)
    resp.raise_for_status()

def main():
    log.info("=" * 55)
    log.info("  GRU Pod Predictor — khởi động")
    log.info(f"  Namespace    : {NAMESPACE}")
    log.info(f"  Deployment   : {TARGET_DEPLOYMENT}")
    log.info(f"  Prometheus   : {PROMETHEUS_URL}")
    log.info(f"  Pushgateway  : {PUSHGATEWAY_URL}")
    log.info(f"  POD_CAPACITY : {POD_CAPACITY}%/pod (=limits.cpu)")
    log.info(f"  SCALE UP/DOWN: >{SCALE_UP_UTIL}% / <{SCALE_DOWN_UTIL}%  target {TARGET_UTIL}%  BUFFER {BUFFER}")
    log.info(f"  MIN/MAX Pods : {MIN_PODS}/{MAX_PODS}")
    log.info(f"  Interval     : {INTERVAL_SEC}s")
    log.info(f"  TESTBED_MODE : {TESTBED_MODE}")
    log.info(f"  Query        : {PROMETHEUS_QUERY}")
    log.info("=" * 55)

    model, scaler, config = load_artifacts()
    look_back    = config["look_back"]
    resample_min = config["resample_min"]

    cycle = 0
    while True:
        cycle += 1
        t_start = time.time()
        log.info(f"── Chu kỳ #{cycle} ──────────────────────")
        try:
            series       = fetch_cpu_history(look_back, resample_min)
            current_pods = fetch_current_pods()
            log.info(f"CPU lịch sử: avg={series.mean():.2f}%  "
                     f"max={series.max():.2f}%  ({len(series)} điểm)")
            tensor        = build_tensor(series, scaler, look_back)
            predicted_cpu = predict_cpu(model, tensor, scaler)
            n_pods        = calc_n_pods(predicted_cpu, current_pods)
            util_pod = (predicted_cpu / max(1, current_pods)) / POD_CAPACITY * 100
            push_to_gateway(predicted_cpu, n_pods, current_pods, util_pod)
            delta  = n_pods - current_pods if current_pods > 0 else 0
            action = (f"SCALE UP +{delta}"   if delta > 0 else
                      f"SCALE DOWN {delta}"  if delta < 0 else "GIỮ NGUYÊN")
            log.info(f"→ {action} | cpu_pred={predicted_cpu:.2f}%  util/pod={util_pod:.0f}%  "
                     f"n_pods={n_pods}  current={current_pods}  "
                     f"({time.time()-t_start:.2f}s)")
        except Exception as e:
            log.error(f"Lỗi chu kỳ #{cycle}: {e}", exc_info=True)
        time.sleep(max(0, INTERVAL_SEC - (time.time() - t_start)))

if __name__ == "__main__":
    main()
