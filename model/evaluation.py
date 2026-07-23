#!/usr/bin/env python3
"""
模型评估工具 — 样本不均衡检测 + K折交叉验证 + 回归指标报告

纯函数，零业务依赖。
"""

import json
from pathlib import Path

import numpy as np


def class_balance_report(scores: list, n_bins: int = 5) -> dict:
    """
    把连续分数分桶，检测各桶样本量是否均衡。

    Returns:
        {"bins": [...], "counts": [...], "balanced": bool, "imbalance_ratio": float}
    """
    scores = np.array(scores, dtype=np.float64)
    bins = np.linspace(0, 100, n_bins + 1)
    counts = []
    labels = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (scores >= lo) & (scores < hi) if i < n_bins - 1 else (scores >= lo) & (scores <= hi)
        counts.append(int(mask.sum()))
        labels.append(f"{int(lo)}-{int(hi)}")

    counts_arr = np.array(counts)
    if counts_arr.sum() == 0:
        return {"bins": labels, "counts": counts, "balanced": False, "imbalance_ratio": 999,
                "message": "No data"}

    max_c = counts_arr.max()
    min_c = counts_arr[counts_arr > 0].min() if (counts_arr > 0).any() else 0
    ratio = float(max_c) / float(min_c) if min_c > 0 else 999
    balanced = ratio < 2.0

    return {
        "bins": labels, "counts": counts, "total": int(counts_arr.sum()),
        "balanced": balanced, "imbalance_ratio": round(ratio, 2),
        "message": "均衡" if balanced else f"不均衡 (ratio={ratio:.1f}x)，建议增加低分桶样本或降采样"
    }


def regression_report(y_true: list, y_pred: list) -> dict:
    """
    完整回归指标。

    Returns:
        {"MAE", "MSE", "RMSE", "R2", "Pearson_r"}
    """
    yt = np.array(y_true, dtype=np.float64)
    yp = np.array(y_pred, dtype=np.float64)

    mae = float(np.abs(yt - yp).mean())
    mse = float(((yt - yp) ** 2).mean())
    rmse = float(np.sqrt(mse))

    ss_res = ((yt - yp) ** 2).sum()
    ss_tot = ((yt - yt.mean()) ** 2).sum()
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Pearson
    corr = float(np.corrcoef(yt, yp)[0, 1]) if len(yt) > 1 else 0.0

    return {"MAE": round(mae, 2), "MSE": round(mse, 4), "RMSE": round(rmse, 2),
            "R2": round(r2, 4), "Pearson_r": round(corr, 4)}


def cross_validate(model_cls, data: tuple, k: int = 5, epochs: int = 10, lr: float = 1e-3) -> dict:
    """
    K折交叉验证。

    Args:
        model_cls: 接受 vocab_size 返回 nn.Module 的可调用对象
        data: (resume_ids, jd_ids, labels)
        k: 折数
        epochs, lr: 训练参数

    Returns:
        {"folds": [{"MAE":..., "R2":...}, ...], "mean_MAE": ..., "std_MAE": ...}
    """
    import torch
    import torch.nn as nn
    from sklearn.model_selection import KFold

    r_ids, j_ids, labels = data
    n = len(labels)
    kf = KFold(n_splits=min(k, n), shuffle=True, random_state=42)

    results = []
    for fold, (tr_idx, vl_idx) in enumerate(kf.split(range(n))):
        tr_r = r_ids[tr_idx]; tr_j = j_ids[tr_idx]; tr_y = labels[tr_idx]
        vl_r = r_ids[vl_idx]; vl_j = j_ids[vl_idx]; vl_y = labels[vl_idx]

        model = model_cls()
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        loss_fn = nn.MSELoss()

        for _ in range(epochs):
            model.train()
            perm = torch.randperm(len(tr_y))
            for i in range(0, len(tr_y), 16):
                idx = perm[i:i+16]
                r_b = tr_r[idx]; j_b = tr_j[idx]; y_b = tr_y[idx] / 100.0
                opt.zero_grad()
                pred = model(r_b, j_b)
                loss = loss_fn(pred, y_b)
                loss.backward(); opt.step()

        model.eval()
        with torch.no_grad():
            vp = model(vl_r, vl_j)
            v_mae = (vp - vl_y / 100.0).abs().mean().item() * 100
            ss_r = ((vp.squeeze() - vl_y / 100.0) ** 2).sum().item()
            ss_t = ((vl_y / 100.0 - vl_y.mean() / 100.0) ** 2).sum().item()
            v_r2 = 1 - ss_r / ss_t if ss_t > 0 else 0.0

        results.append({"fold": fold + 1, "n_train": len(tr_y), "n_val": len(vl_y),
                        "MAE": round(v_mae, 2), "R2": round(v_r2, 4)})

    maes = [r["MAE"] for r in results]
    r2s = [r["R2"] for r in results]
    return {"folds": results, "mean_MAE": round(np.mean(maes), 2), "std_MAE": round(np.std(maes), 2),
            "mean_R2": round(np.mean(r2s), 4), "std_R2": round(np.std(r2s), 4)}


def confusion_like_report(y_true: list, y_pred: list, threshold: float = 70) -> dict:
    """
    按阈值将回归转为二分类，输出类似混淆矩阵的统计。

    Returns:
        {"TP": ..., "FP": ..., "TN": ..., "FN": ..., "precision": ..., "recall": ..., "f1": ...}
    """
    yt = np.array(y_true)
    yp = np.array(y_pred)
    pos_true = yt >= threshold
    pos_pred = yp >= threshold
    tp = int((pos_true & pos_pred).sum())
    fp = int((~pos_true & pos_pred).sum())
    tn = int((~pos_true & ~pos_pred).sum())
    fn = int((pos_true & ~pos_pred).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    return {"TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def calibration_curve(y_true: list, y_pred: list, n_bins: int = 10) -> dict:
    """校准曲线分桶数据 — 每桶真实均值 vs 预测均值"""
    yt = np.array(y_true); yp = np.array(y_pred)
    bins = np.linspace(0, 100, n_bins + 1)
    result = {"bins": [], "true_mean": [], "pred_mean": [], "count": []}
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (yp >= lo) & (yp < hi) if i < n_bins - 1 else (yp >= lo) & (yp <= hi)
        if mask.sum() > 0:
            result["bins"].append(f"{int(lo)}-{int(hi)}")
            result["true_mean"].append(round(float(yt[mask].mean()), 1))
            result["pred_mean"].append(round(float(yp[mask].mean()), 1))
            result["count"].append(int(mask.sum()))
    return result
