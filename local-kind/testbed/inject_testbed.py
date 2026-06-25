#!/usr/bin/env python3
"""
inject_testbed.py — Bơm metric `testbed_cpu_usage` vào Pushgateway để mô phỏng tải CPU,
cho phép test autoscaling của model GRU.
"""
import argparse, csv, math, sys, time, urllib.request

def push(pushgateway, namespace, value):
    url = f"{pushgateway}/metrics/job/testbed/namespace/{namespace}"
    body = (
        "# HELP testbed_cpu_usage Synthetic CPU usage for autoscaling testbed (%)\n"
        "# TYPE testbed_cpu_usage gauge\n"
        f"testbed_cpu_usage {value:.4f}\n"
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "text/plain"})
    urllib.request.urlopen(req, timeout=5).read()

def run_wave(a):
    print(f"[wave] low={a.low}% high={a.high}% period={a.period}s interval={a.interval}s -> {a.pushgateway}")
    t0 = time.time()
    while True:
        t = time.time() - t0
        # sin chạy từ low (t=0) lên high rồi về low, lặp lại theo period
        frac = 0.5 - 0.5 * math.cos(2 * math.pi * t / a.period)
        value = a.low + (a.high - a.low) * frac
        push(a.pushgateway, a.namespace, value)
        print(f"  t={t:6.0f}s  testbed_cpu_usage={value:6.2f}%")
        time.sleep(a.interval)

def run_replay(a):
    rows = []
    with open(a.csv, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                rows.append(float(r[a.col]))
            except (KeyError, ValueError):
                pass
    if not rows:
        sys.exit(f"Không đọc được giá trị từ cột '{a.col}' trong {a.csv}")
    # Chỉ replay từ vị trí start_frac trở đi (vd 0.90 = đúng test set 10% cuối,
    # phần model CHƯA hề train -> demo online không bị 'học thuộc').
    if a.start_frac > 0:
        cut = int(len(rows) * a.start_frac)
        print(f"[replay] bỏ {cut} điểm đầu (frac={a.start_frac}); chỉ replay {len(rows)-cut} điểm cuối (dữ liệu model chưa thấy)")
        rows = rows[cut:]
    print(f"[replay] {len(rows)} điểm từ {a.csv} (cột {a.col}), interval={a.interval}s, loop={a.loop}")
    i = 0
    while True:
        value = rows[i]
        push(a.pushgateway, a.namespace, value)
        print(f"  [{i+1}/{len(rows)}] testbed_cpu_usage={value:6.2f}%")
        i += 1
        if i >= len(rows):
            if not a.loop:
                break
            i = 0
        time.sleep(a.interval)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["wave", "replay"])
    p.add_argument("--pushgateway", default="http://localhost:30060")
    p.add_argument("--namespace", default="carserv")
    p.add_argument("--interval", type=float, default=300.0,
                   help="giây giữa 2 lần đẩy (mặc định 300s = 5 phút, khớp resample_min=5 của model)")
    # wave
    p.add_argument("--low", type=float, default=5.0)
    p.add_argument("--high", type=float, default=130.0)
    p.add_argument("--period", type=float, default=7200.0,
                   help="chu kỳ sóng (giây); 7200s=2h ~ trọn một cửa sổ GRU 120 phút")
    # replay
    p.add_argument("--csv", default="/mnt/d/DATN/Tổng hợp/Train mô hình/data_host_5m_filtered.csv")
    p.add_argument("--col", default="host_cpu_usage")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--start-frac", dest="start_frac", type=float, default=0.0,
                   help="Chỉ replay từ vị trí này trở đi (0.90 = test set 10%% cuối, model chưa thấy)")
    a = p.parse_args()
    try:
        (run_wave if a.mode == "wave" else run_replay)(a)
    except KeyboardInterrupt:
        print("\nĐã dừng injector.")
