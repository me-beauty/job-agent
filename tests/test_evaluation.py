#!/usr/bin/env python3
"""单元测试：评估工具"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from model.evaluation import class_balance_report, regression_report, confusion_like_report, calibration_curve


def test_balance_balanced():
    """均衡数据检测"""
    scores = [20, 30, 50, 60, 80, 90, 25, 35, 55, 65]
    r = class_balance_report(scores, n_bins=3)
    assert "bins" in r and "balanced" in r
    assert r["total"] == 10


def test_balance_imbalanced():
    """不均衡数据检测"""
    scores = [90] * 20 + [10, 20, 30, 40, 50]
    r = class_balance_report(scores, n_bins=3)
    assert r["imbalance_ratio"] >= 1.0


def test_regression_report():
    """回归指标计算"""
    y_true = [50, 60, 70, 80, 90]
    y_pred = [48, 62, 68, 82, 88]
    r = regression_report(y_true, y_pred)
    assert "MAE" in r and "R2" in r
    assert r["MAE"] < 5


def test_confusion_like():
    """阈值分类报告"""
    yt = [80, 90, 60, 50, 30, 85, 75, 40]
    yp = [75, 85, 55, 55, 35, 80, 70, 45]
    r = confusion_like_report(yt, yp, threshold=70)
    assert "precision" in r and "recall" in r


def test_calibration():
    """校准曲线分桶"""
    yt = [10, 20, 50, 60, 90]
    yp = [12, 22, 48, 62, 88]
    r = calibration_curve(yt, yp, n_bins=5)
    assert "bins" in r and "true_mean" in r


if __name__ == "__main__":
    test_balance_balanced();    print("✅ balance_balanced")
    test_balance_imbalanced();  print("✅ balance_imbalanced")
    test_regression_report();   print("✅ regression_report")
    test_confusion_like();      print("✅ confusion_like")
    test_calibration();         print("✅ calibration")
    print("\n🎉 All eval tests passed!")
