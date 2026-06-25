#!/usr/bin/env python3
"""
fix_model.py — Gỡ trường 'quantization_config' (giá trị None, vô hại) khỏi phần
config trong file model .keras, để các phiên bản Keras khác load được.

File .keras là 1 zip gồm: config.json (kiến trúc) + model.weights.h5 (trọng số) + metadata.json.
Script CHỈ sửa config.json, KHÔNG đụng tới trọng số -> model giữ nguyên độ chính xác.
Chỉ dùng thư viện chuẩn (zipfile, json) -> KHÔNG cần tensorflow/keras để chạy.

Cách dùng:
    python fix_model.py <input.keras> <output.keras>
"""
import zipfile, json, sys

if len(sys.argv) != 3:
    print("Usage: python fix_model.py <input.keras> <output.keras>")
    sys.exit(1)

SRC, DST = sys.argv[1], sys.argv[2]

def strip_key(obj, key="quantization_config"):
    """Đệ quy xóa mọi khóa 'quantization_config' trong dict/list lồng nhau."""
    if isinstance(obj, dict):
        obj.pop(key, None)
        for v in obj.values():
            strip_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            strip_key(v, key)

# Đọc toàn bộ thành phần trong file .keras (zip)
with zipfile.ZipFile(SRC, "r") as z:
    members = {n: z.read(n) for n in z.namelist()}

# Làm sạch mọi file .json (config.json là nơi chứa quantization_config)
cleaned = 0
for name in list(members):
    if name.endswith(".json"):
        obj = json.loads(members[name].decode("utf-8"))
        strip_key(obj)
        members[name] = json.dumps(obj).encode("utf-8")
        cleaned += 1

# Ghi ra file .keras mới (giữ nguyên model.weights.h5)
with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
    for name, blob in members.items():
        z.writestr(name, blob)

print(f"OK: đã xử lý {cleaned} file json, ghi model mới -> {DST}")
