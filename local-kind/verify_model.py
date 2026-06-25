#!/usr/bin/env python3
"""verify_model.py — Thử load model .keras và in input_shape. Dùng để kiểm tra
nhanh model đã load được chưa, tránh lỗi xuống dòng khi dán lệnh python -c dài.

Cách dùng:  python verify_model.py <path_toi_file.keras>
"""
import sys
import keras

path = sys.argv[1] if len(sys.argv) > 1 else "model/gru_cpu_model_fixed.keras"
model = keras.models.load_model(path)
print("LOAD OK |", path, "| input_shape =", model.input_shape)
