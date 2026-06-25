#!/usr/bin/env python3
"""
cpuapp.py — Web service ĐỐT CPU mỗi request (thay carserv tĩnh để k6 tạo CPU thật).
Chỉ dùng thư viện chuẩn -> KHÔNG cần pip (build nhanh, không cần mạng).

Mỗi GET / chạy một vòng lặp tính toán WORK_ITERS lần -> tốn CPU.
Chỉnh WORK_ITERS để 1 request "nặng" hơn/nhẹ hơn (ảnh hưởng ánh xạ RPS->CPU).
Lắng nghe cổng 80 (chạy root nên bind được).
"""
import os, math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORK = int(os.getenv("WORK_ITERS", "150000"))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        x = 0.0
        for i in range(WORK):
            x += math.sqrt((i % 97) + 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok\n")
    def log_message(self, *args):
        pass  # tắt log cho đỡ ồn

if __name__ == "__main__":
    print(f"cpuapp listening :80  (WORK_ITERS={WORK})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
