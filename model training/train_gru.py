"""
GRU CPU Usage Forecasting — Kubernetes Autoscaling (KEDA)
==========================================================
Huấn luyện và đánh giá mô hình GRU dự báo CPU Usage theo chuỗi thời gian
5 phút, phục vụ autoscaling chủ động trên Kubernetes thông qua KEDA.

Dataset  : data_host_5m_filtered.csv
Author   : Đồ án tốt nghiệp
Python   : 3.12+  (tương thích 3.13)
"""

import os
import pickle
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # render không cần màn hình (headless)
import matplotlib.pyplot as plt

from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import GRU, Dense, Dropout, Input, BatchNormalization
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.regularizers import l2

warnings.filterwarnings("ignore")

# ════════════════════════════════════════════════════════════════════
#  HYPERPARAMETERS — chỉnh tại đây để xử lý underfit / overfit
# ════════════════════════════════════════════════════════════════════

# ── Dữ liệu ─────────────────────────────────────────────────────────
CSV_PATH    = "data_host_5m_filtered.csv"
LOOK_BACK   = 24          # 24 × 5 phút = 2 giờ lịch sử
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
TEST_RATIO  = 0.10 

# ── Kiến trúc GRU ────────────────────────────────────────────────────
GRU_UNITS_1      = 50     # số units lớp GRU thứ nhất  ↑ → capacity tăng (underfit)
GRU_UNITS_2      = 50     # số units lớp GRU thứ hai
DENSE_UNITS      = 25     # số units lớp Dense ẩn
DROPOUT_RATE     = 0.2   # tỉ lệ dropout  ↑ → regularize mạnh hơn (overfit)
USE_BATCH_NORM   = False   # True → thêm BatchNormalization sau mỗi GRU (hỗ trợ training ổn định)
L2_REG           = 0.001    # hệ số L2 regularization  ↑ → penalize weight lớn (overfit)
                           # ví dụ: 0.001

# ── Huấn luyện ───────────────────────────────────────────────────────
EPOCHS        = 100
BATCH_SIZE    = 32        # ↓ → gradient noise nhiều hơn (có thể giúp thoát local minima)
LEARNING_RATE = 1e-4      # ↓ → học chậm hơn, có thể hội tụ tốt hơn
PATIENCE_ES   = 20       # EarlyStopping patience  ↑ → cho phép train lâu hơn
PATIENCE_LR   = 5         # ReduceLROnPlateau patience
LR_FACTOR     = 0.45       # hệ số giảm learning rate khi plateau


# ════════════════════════════════════════════════════════════════════
#  1. LOAD DATA
# ════════════════════════════════════════════════════════════════════
def load_data(csv_path: str) -> pd.DataFrame:
    """
    Đọc file CSV đã tiền xử lý.
    - parse cột timestamp thành datetime
    - chỉ giữ 2 cột cần thiết: timestamp, host_cpu_usage
    - sort theo thứ tự thời gian tăng dần
    """
    print(f"\n[DATA] Đang đọc dữ liệu từ '{csv_path}' ...")
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = (df[["timestamp", "host_cpu_usage"]]
            .sort_values("timestamp")
            .reset_index(drop=True))

    print(f"[DATA] Tổng số mẫu  : {len(df):,}")
    print(f"[DATA] Khoảng thời gian: {df['timestamp'].iloc[0]}  →  {df['timestamp'].iloc[-1]}")
    print(f"[DATA] CPU Usage (%):\n{df['host_cpu_usage'].describe().round(2).to_string()}\n")
    return df


# ════════════════════════════════════════════════════════════════════
#  2. CREATE SEQUENCES
# ════════════════════════════════════════════════════════════════════
def create_sequences(data: np.ndarray, look_back: int):
    """
    Sinh chuỗi huấn luyện theo kỹ thuật sliding window.

    Tham số
    -------
    data      : mảng 2D (n_samples, 1) đã được chuẩn hóa
    look_back : độ dài cửa sổ (LOOK_BACK = 24 bước = 2 giờ)

    Kết quả
    -------
    X : (samples, look_back, 1)  — chuỗi đầu vào
    y : (samples, 1)             — giá trị cần dự báo (bước tiếp theo)
    """
    X, y = [], []
    for i in range(len(data) - look_back):
        X.append(data[i : i + look_back])      # cửa sổ look_back bước
        y.append(data[i + look_back])           # nhãn: bước kế tiếp
    return np.array(X), np.array(y)


# ════════════════════════════════════════════════════════════════════
#  3. BUILD GRU MODEL
# ════════════════════════════════════════════════════════════════════
def build_gru_model(look_back: int) -> tf.keras.Model:
    """
    Xây dựng mô hình GRU hai lớp với các tham số có thể hiệu chỉnh.

    Kiến trúc cơ bản:
        Input(look_back, 1)
        GRU(GRU_UNITS_1, return_sequences=True)  [+ BatchNorm nếu bật]
        Dropout(DROPOUT_RATE)
        GRU(GRU_UNITS_2)                          [+ BatchNorm nếu bật]
        Dropout(DROPOUT_RATE)
        Dense(DENSE_UNITS, relu)
        Dense(1)

    Hướng dẫn hiệu chỉnh:
    ─────────────────────
    Underfit (loss cao ở cả train & val):
      • Tăng GRU_UNITS_1, GRU_UNITS_2 (ví dụ 64, 128)
      • Tăng DENSE_UNITS (ví dụ 64)
      • Giảm DROPOUT_RATE (ví dụ 0.1)
      • Giảm L2_REG về 0.0
      • Tăng EPOCHS, giảm PATIENCE_ES

    Overfit (train loss thấp, val loss cao):
      • Tăng DROPOUT_RATE (ví dụ 0.3–0.5)
      • Bật USE_BATCH_NORM = True
      • Tăng L2_REG (ví dụ 0.001)
      • Giảm GRU_UNITS (ví dụ 32)
      • Tăng PATIENCE_ES để EarlyStopping bắt đúng điểm dừng
    """
    reg = l2(L2_REG) if L2_REG > 0 else None   # kernel regularizer tùy chọn

    layers = [Input(shape=(look_back, 1))]

    # ── Lớp GRU 1 ────────────────────────────────────────────────────
    layers.append(GRU(
        GRU_UNITS_1,
        return_sequences=True,          # trả chuỗi để lớp GRU 2 tiếp nhận
        kernel_regularizer=reg,
    ))
    if USE_BATCH_NORM:
        layers.append(BatchNormalization())
    layers.append(Dropout(DROPOUT_RATE))

    # ── Lớp GRU 2 ────────────────────────────────────────────────────
    layers.append(GRU(
        GRU_UNITS_2,
        return_sequences=False,         # chỉ lấy hidden state cuối cùng
        kernel_regularizer=reg,
    ))
    if USE_BATCH_NORM:
        layers.append(BatchNormalization())
    layers.append(Dropout(DROPOUT_RATE))

    # ── Đầu ra ───────────────────────────────────────────────────────
    layers.append(Dense(DENSE_UNITS, activation="relu"))
    layers.append(Dense(1))

    model = Sequential(layers, name="GRU_CPU_Model")

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss="mse",
        metrics=["mae"],
    )
    return model


# ════════════════════════════════════════════════════════════════════
#  4. EVALUATE MODEL
# ════════════════════════════════════════════════════════════════════
def evaluate_model(y_true: np.ndarray, y_pred: np.ndarray, split_name: str) -> dict:
    """
    Tính 4 chỉ số đánh giá trên dữ liệu đã inverse-transform (đơn vị gốc %).

    RMSE  — độ lệch bình phương trung bình (nhạy với outlier)
    MAE   — độ lệch tuyệt đối trung bình
    MAPE  — phần trăm lệch trung bình (bỏ qua vị trí có giá trị = 0)
    R²    — hệ số xác định (1.0 = hoàn hảo, < 0 = tệ hơn đường trung bình)
    """
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mae  = mean_absolute_error(y_true, y_pred)

    # MAPE: tránh chia cho 0
    mask = y_true != 0
    mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100

    r2 = r2_score(y_true, y_pred)

    print(f"  [{split_name:^10}]  RMSE={rmse:.4f}  MAE={mae:.4f}  "
          f"MAPE={mape:.2f}%  R²={r2:.4f}")
    return {"RMSE": rmse, "MAE": mae, "MAPE": mape, "R2": r2}


# ════════════════════════════════════════════════════════════════════
#  5. VISUALIZATION
# ════════════════════════════════════════════════════════════════════
def plot_results(
    history,
    y_val_true:  np.ndarray,
    y_val_pred:  np.ndarray,
    y_test_true: np.ndarray,
    y_test_pred: np.ndarray,
) -> None:
    """
    Vẽ và lưu 6 biểu đồ đánh giá mô hình GRU:
      1. Loss Curves
      2. Validation — Actual vs Predicted
      3. Test       — Actual vs Predicted
      4. Residual Plot (Test)
      5. Residual Histogram (Test)
      6. Scatter Plot (Test)
    """
    LABEL = "GRU"
    COLOR_ACT  = "#2196F3"   # xanh dương — actual
    COLOR_PRED = "#F44336"   # đỏ         — predicted
    COLOR_RES  = "#4CAF50"   # xanh lá    — residual

    # ── 1. Loss Curves ───────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(history.history["loss"],     label="Train Loss", color=COLOR_ACT,  linewidth=1.5)
    ax.plot(history.history["val_loss"], label="Val Loss",   color=COLOR_PRED, linewidth=1.5)
    best_ep = int(np.argmin(history.history["val_loss"]))
    ax.axvline(best_ep, color="gray", linestyle=":", linewidth=1,
               label=f"Best epoch ({best_ep+1})")
    ax.set_title(f"{LABEL} — Training & Validation Loss (MSE)")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("MSE Loss")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("gru_loss_curve.png", dpi=150)
    plt.close(fig)
    print("[PLOT] gru_loss_curve.png")

    # ── 2. Validation: Actual vs Predicted ──────────────────────────
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(y_val_true, label="Actual",    color=COLOR_ACT,  linewidth=1,   alpha=0.9)
    ax.plot(y_val_pred, label="Predicted", color=COLOR_PRED, linewidth=1,   alpha=0.85, linestyle="--")
    ax.set_title(f"{LABEL} — Validation Set: Actual vs Predicted")
    ax.set_xlabel("Time Step")
    ax.set_ylabel("CPU Usage (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("gru_validation_prediction.png", dpi=150)
    plt.close(fig)
    print("[PLOT] gru_validation_prediction.png")

    # ── 3. Test: Actual vs Predicted ────────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(y_test_true, label="Actual",    color=COLOR_ACT,  linewidth=1,   alpha=0.9)
    ax.plot(y_test_pred, label="Predicted", color=COLOR_PRED, linewidth=1,   alpha=0.85, linestyle="--")
    ax.set_title(f"{LABEL} — Test Set: Actual vs Predicted")
    ax.set_xlabel("Time Step")
    ax.set_ylabel("CPU Usage (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("gru_test_prediction.png", dpi=150)
    plt.close(fig)
    print("[PLOT] gru_test_prediction.png")

    # ── 4. Residual Plot (Test) ──────────────────────────────────────
    residuals = y_test_true - y_test_pred
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(residuals, color=COLOR_RES, linewidth=0.8, alpha=0.8, label="Residual")
    ax.axhline(0, color="red", linestyle="--", linewidth=1, label="Zero line")
    ax.fill_between(range(len(residuals)), residuals, 0,
                    where=(residuals > 0), color=COLOR_RES, alpha=0.15)
    ax.fill_between(range(len(residuals)), residuals, 0,
                    where=(residuals < 0), color=COLOR_PRED, alpha=0.15)
    ax.set_title(f"{LABEL} — Test Residuals (Actual − Predicted)")
    ax.set_xlabel("Time Step")
    ax.set_ylabel("Residual (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("gru_residual_plot.png", dpi=150)
    plt.close(fig)
    print("[PLOT] gru_residual_plot.png")

    # ── 5. Residual Histogram ────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(residuals, bins=50, color=COLOR_RES, edgecolor="white", alpha=0.85)
    ax.axvline(0,                 color="red",  linestyle="--", linewidth=1.5, label="Zero")
    ax.axvline(residuals.mean(),  color="navy", linestyle="-",  linewidth=1.2,
               label=f"Mean={residuals.mean():.3f}")
    ax.set_title(f"{LABEL} — Residual Distribution (Test)")
    ax.set_xlabel("Residual (%)")
    ax.set_ylabel("Frequency")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("gru_residual_histogram.png", dpi=150)
    plt.close(fig)
    print("[PLOT] gru_residual_histogram.png")

    # ── 6. Scatter Plot ──────────────────────────────────────────────
    all_vals = np.concatenate([y_test_true, y_test_pred])
    lim = (all_vals.min() * 0.97, all_vals.max() * 1.03)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_test_true, y_test_pred, alpha=0.25, s=8, color=COLOR_ACT, label="Samples")
    ax.plot(lim, lim, "r--", linewidth=1.5, label="y = x (perfect)")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_title(f"{LABEL} — Actual vs Predicted Scatter (Test)")
    ax.set_xlabel("Actual CPU Usage (%)")
    ax.set_ylabel("Predicted CPU Usage (%)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("gru_actual_vs_predicted_scatter.png", dpi=150)
    plt.close(fig)
    print("[PLOT] gru_actual_vs_predicted_scatter.png")


# ════════════════════════════════════════════════════════════════════
#  6. MAIN
# ════════════════════════════════════════════════════════════════════
def main():
    # ── Seed tái lập kết quả ─────────────────────────────────────────
    tf.random.set_seed(42)
    np.random.seed(42)

    # ── In cấu hình đang dùng ────────────────────────────────────────
    print("=" * 60)
    print("  GRU CPU Forecasting — Cấu hình hiện tại")
    print("=" * 60)
    print(f"  LOOK_BACK      = {LOOK_BACK}")
    print(f"  GRU_UNITS      = ({GRU_UNITS_1}, {GRU_UNITS_2})")
    print(f"  DENSE_UNITS    = {DENSE_UNITS}")
    print(f"  DROPOUT_RATE   = {DROPOUT_RATE}")
    print(f"  USE_BATCH_NORM = {USE_BATCH_NORM}")
    print(f"  L2_REG         = {L2_REG}")
    print(f"  EPOCHS         = {EPOCHS}  (EarlyStopping patience={PATIENCE_ES})")
    print(f"  BATCH_SIZE     = {BATCH_SIZE}")
    print(f"  LEARNING_RATE  = {LEARNING_RATE}")
    print("=" * 60)

    # ── 1. Load dữ liệu ──────────────────────────────────────────────
    df = load_data(CSV_PATH)
    values = df["host_cpu_usage"].values.reshape(-1, 1)
    timestamps = df["timestamp"].values
    n = len(values)

    # ── 2. Chia train / val / test (chronological) ───────────────────
    n_train = int(n * TRAIN_RATIO)
    n_val   = int(n * VAL_RATIO)
    n_test  = n - n_train - n_val

    train_raw = values[:n_train]
    val_raw   = values[n_train : n_train + n_val]
    test_raw  = values[n_train + n_val :]

    print(f"[SPLIT] Train={n_train:,}  Val={n_val:,}  Test={n_test:,}  "
          f"(tổng={n:,})")

    # ── 3. Chuẩn hóa MinMax — scaler chỉ fit trên Train ─────────────
    scaler = MinMaxScaler(feature_range=(0, 1))
    train_scaled = scaler.fit_transform(train_raw)
    val_scaled   = scaler.transform(val_raw)
    test_scaled  = scaler.transform(test_raw)

    with open("scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)
    print("[SCALER] Đã lưu → scaler.pkl")
    print(f"[SCALER] data_min={scaler.data_min_[0]:.4f}  "
          f"data_max={scaler.data_max_[0]:.4f}\n")

    # ── 4. Sinh chuỗi sliding window ─────────────────────────────────
    X_train, y_train = create_sequences(train_scaled, LOOK_BACK)
    X_val,   y_val   = create_sequences(val_scaled,   LOOK_BACK)
    X_test,  y_test  = create_sequences(test_scaled,  LOOK_BACK)

    print(f"[SEQ] X_train={X_train.shape}  y_train={y_train.shape}")
    print(f"[SEQ] X_val  ={X_val.shape}    y_val  ={y_val.shape}")
    print(f"[SEQ] X_test ={X_test.shape}   y_test ={y_test.shape}\n")

    # Lấy timestamp tương ứng với từng prediction
    val_ts  = timestamps[n_train + LOOK_BACK : n_train + LOOK_BACK + len(y_val)]
    test_ts = timestamps[n_train + n_val + LOOK_BACK : n_train + n_val + LOOK_BACK + len(y_test)]

    # ── 5. Xây dựng mô hình ──────────────────────────────────────────
    print("[MODEL] Xây dựng kiến trúc GRU ...")
    model = build_gru_model(LOOK_BACK)
    model.summary()

    # ── 6. Callbacks ─────────────────────────────────────────────────
    early_stop = EarlyStopping(
        monitor="val_loss",
        patience=PATIENCE_ES,
        restore_best_weights=True,
        verbose=1,
    )
    checkpoint = ModelCheckpoint(
        filepath="gru_cpu_model.keras",
        monitor="val_loss",
        save_best_only=True,
        verbose=1,
    )
    reduce_lr = ReduceLROnPlateau(
        monitor="val_loss",
        factor=LR_FACTOR,
        patience=PATIENCE_LR,
        min_lr=1e-6,
        verbose=1,
    )

    # ── 7. Huấn luyện ────────────────────────────────────────────────
    print(f"\n[TRAIN] Bắt đầu huấn luyện (tối đa {EPOCHS} epochs) ...")
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        callbacks=[early_stop, checkpoint, reduce_lr],
        verbose=1,
    )

    stopped_epoch = len(history.history["loss"])
    best_epoch    = int(np.argmin(history.history["val_loss"])) + 1
    best_val_loss = min(history.history["val_loss"])
    print(f"\n[TRAIN] Dừng ở epoch {stopped_epoch}  |  "
          f"Best epoch={best_epoch}  Best val_loss={best_val_loss:.6f}")
    print("[TRAIN] Model đã lưu → gru_cpu_model.keras\n")

    # ── 8. Dự báo & Inverse-transform ────────────────────────────────
    val_pred_scaled  = model.predict(X_val,  verbose=0)
    test_pred_scaled = model.predict(X_test, verbose=0)

    y_val_true  = scaler.inverse_transform(y_val).flatten()
    y_val_pred  = scaler.inverse_transform(val_pred_scaled).flatten()
    y_test_true = scaler.inverse_transform(y_test).flatten()
    y_test_pred = scaler.inverse_transform(test_pred_scaled).flatten()

    # ── 9. Đánh giá ──────────────────────────────────────────────────
    print("[EVAL] Kết quả đánh giá mô hình GRU:")
    print("-" * 58)
    val_metrics  = evaluate_model(y_val_true,  y_val_pred,  "Validation")
    test_metrics = evaluate_model(y_test_true, y_test_pred, "Test")
    print("-" * 58)

    # ── 10. Biểu đồ ──────────────────────────────────────────────────
    print("\n[PLOT] Đang lưu biểu đồ ...")
    plot_results(history, y_val_true, y_val_pred, y_test_true, y_test_pred)

    # ── 11. Lưu CSV kết quả ──────────────────────────────────────────
    df_val_out = pd.DataFrame({
        "timestamp":      val_ts,
        "split":          "validation",
        "actual":         y_val_true,
        "predicted":      y_val_pred,
        "residual":       y_val_true - y_val_pred,
        "absolute_error": np.abs(y_val_true - y_val_pred),
    })
    df_test_out = pd.DataFrame({
        "timestamp":      test_ts,
        "split":          "test",
        "actual":         y_test_true,
        "predicted":      y_test_pred,
        "residual":       y_test_true - y_test_pred,
        "absolute_error": np.abs(y_test_true - y_test_pred),
    })
    df_pred = pd.concat([df_val_out, df_test_out], ignore_index=True)
    df_pred.to_csv("gru_predictions.csv", index=False)
    print("[CSV] gru_predictions.csv")

    # ── 12. Báo cáo tổng kết ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  GRU MODEL — BÁO CÁO ĐÁNH GIÁ CUỐI CÙNG")
    print(f"{'='*60}")
    print(f"  {'Chỉ số':<14}  {'Validation':>12}  {'Test':>12}")
    print(f"  {'-'*44}")
    for key, label in [("RMSE","RMSE"), ("MAE","MAE"),
                        ("MAPE","MAPE (%)"), ("R2","R²")]:
        v = val_metrics[key]
        t = test_metrics[key]
        unit = " %" if key == "MAPE" else ""
        print(f"  {label:<14}  {v:>11.4f}  {t:>11.4f}{unit}")
    print(f"{'='*60}")
    print(f"  Best epoch    : {best_epoch} / {stopped_epoch}")
    print(f"  Best val_loss : {best_val_loss:.6f}")
    print(f"{'='*60}")

    # Gợi ý hiệu chỉnh dựa trên kết quả
    gap = val_metrics["RMSE"] - test_metrics["RMSE"]
    if test_metrics["R2"] < 0.85:
        print("\n  ⚠  R² thấp — có thể UNDERFIT.")
        print("     → Thử tăng GRU_UNITS, DENSE_UNITS hoặc LOOK_BACK.")
    elif abs(gap) > 2.0:
        print("\n  ⚠  Khoảng cách Val/Test RMSE lớn — kiểm tra phân phối dữ liệu.")
    else:
        print("\n  ✓  Mô hình hội tụ tốt.")

    train_final = history.history["loss"][-1]
    val_final   = history.history["val_loss"][-1]
    overfit_gap = val_final - train_final
    if overfit_gap > 0.01:
        print(f"  ⚠  OVERFIT (train_loss={train_final:.5f}, val_loss={val_final:.5f}).")
        print("     → Thử tăng DROPOUT_RATE, L2_REG hoặc bật USE_BATCH_NORM=True.")

    print(f"\n[DONE] Hoàn tất. Các file đã lưu:")
    for f in [
        "scaler.pkl", "gru_cpu_model.keras", "gru_predictions.csv",
        "gru_loss_curve.png", "gru_validation_prediction.png",
        "gru_test_prediction.png", "gru_residual_plot.png",
        "gru_residual_histogram.png", "gru_actual_vs_predicted_scatter.png",
    ]:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"    {f:<45}  ({size:,} bytes)")


# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
