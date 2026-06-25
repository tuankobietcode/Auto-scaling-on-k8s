#!/usr/bin/env bash
# cpu.sh — Đọc CPU% hiện tại của container carserv (đúng series container="carserv",
#          không đếm trùng cgroup mức pod). Dùng khi hiệu chỉnh RPS->CPU.
# Cách dùng:  bash local-kind/testbed/k6/cpu.sh
PROM="${PROM:-http://localhost:30090}"
WIN="${WIN:-2m}"   # cửa sổ rate; nới rộng nếu scrape thưa (rate[1m] hay rỗng). Dùng: WIN=3m bash cpu.sh
Q="sum(rate(container_cpu_usage_seconds_total{namespace=\"carserv\",pod=~\"carserv-deploy-.*\",container=\"carserv\"}[$WIN]))*100"
curl -s "$PROM/api/v1/query" --data-urlencode "query=$Q" \
 | python3 -c "import sys,json;d=json.load(sys.stdin);r=d.get('data',{}).get('result',[]);print('CPU% =', round(float(r[0]['value'][1]),2) if r else 'EMPTY -> '+str(d))"
