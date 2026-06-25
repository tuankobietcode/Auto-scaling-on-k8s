#!/usr/bin/env python3
"""
gen_k6_from_trace.py — Sinh kịch bản k6 tái hiện trace CPU của data_host.

Ý tưởng: với mỗi điểm CPU mục tiêu C trong file train, đảo ánh xạ tuyến tính đã hiệu chỉnh
    C = a * RPS + b   ->   RPS = (C - b) / a
để ra số request/giây cần bắn. Ghép thành kịch bản 'ramping-arrival-rate' của k6.

Chỉ dùng thư viện chuẩn. Trước khi chạy phải có a, b từ bước hiệu chỉnh (calibrate.js).

Ví dụ:
  python3 gen_k6_from_trace.py \
      --csv "/mnt/d/DATN/Tổng hợp/Train mô hình/data_host_5m_filtered.csv" \
      --col host_cpu_usage --start-frac 0.90 \
      --a 0.85 --b 2.0 --seconds-per-point 30 \
      --out load_from_trace.js
"""
import csv, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--csv", required=True)
ap.add_argument("--col", default="host_cpu_usage")
ap.add_argument("--start-frac", dest="start_frac", type=float, default=0.90,
                help="0.90 = chỉ dùng test set 10%% cuối (model chưa thấy)")
ap.add_argument("--a", type=float, required=True, help="hệ số góc CPU=a*RPS+b (từ hiệu chỉnh)")
ap.add_argument("--b", type=float, default=0.0, help="hệ số chặn (CPU idle, từ hiệu chỉnh)")
ap.add_argument("--seconds-per-point", dest="spp", type=int, default=30,
                help="mỗi điểm 5 phút của trace kéo dài bao nhiêu giây thực (nén thời gian)")
ap.add_argument("--max-rps", type=float, default=500, help="trần RPS an toàn")
ap.add_argument("--base-url", default="http://localhost:30080")
ap.add_argument("--out", default="load_from_trace.js")
a = ap.parse_args()

# Đọc cột CPU, cắt lấy phần start_frac trở đi
vals = []
with open(a.csv, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        try: vals.append(float(r[a.col]))
        except (KeyError, ValueError): pass
cut = int(len(vals) * a.start_frac)
vals = vals[cut:]
if not vals:
    raise SystemExit("Không có dữ liệu sau khi cắt start_frac.")

# Đảo ánh xạ CPU -> RPS
stages = []
for c in vals:
    rps = (c - a.b) / a.a
    rps = max(0, min(a.max_rps, rps))
    stages.append((int(round(rps)), a.spp))   # k6 ramping-arrival-rate yêu cầu target là số NGUYÊN

stages_js = ",\n".join(f'        {{ target: {r}, duration: "{d}s" }}' for r, d in stages)

script = f'''// load_from_trace.js — k6 TÁI HIỆN trace CPU của data_host (test set).
// Sinh tự động bởi gen_k6_from_trace.py | a={a.a}, b={a.b}, start_frac={a.start_frac},
//   {len(stages)} điểm, mỗi điểm {a.spp}s  (tổng ~{len(stages)*a.spp//60} phút)
import http from "k6/http";

export const options = {{
  scenarios: {{
    trace: {{
      executor: "ramping-arrival-rate",
      startRate: {stages[0][0]},
      timeUnit: "1s",
      preAllocatedVUs: 100,
      maxVUs: 2000,
      stages: [
{stages_js}
      ],
    }},
  }},
}};

export default function () {{
  http.get("{a.base_url}");
}}
'''

with open(a.out, "w", encoding="utf-8") as f:
    f.write(script)
print(f"Đã ghi {a.out}: {len(stages)} stage, mỗi stage {a.spp}s, RPS từ {min(s[0] for s in stages)} đến {max(s[0] for s in stages)}")
