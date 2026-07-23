#!/usr/bin/env python3
"""
tf_match_model — PyTorch 人岗匹配打分模型

独立模块，基于 PyTorch 双塔 BiLSTM，兼容 CPU-only 环境。
提供：数据管线 / 训练 / 推理 三合一。

分层调度：
  L1: DeepSeek → 文本预处理
  L2: PyTorch → 本地训练
  L3: Claude → 训练指标分析
  L4: PyTorch → 推理打分

作者: Job Agent / MIT
"""

from .data_pipeline import JobDataPipeline
from .train import train_model
from .inference import calculate_match, rank_jobs, load_model

def is_model_ready() -> bool:
    from . import inference
    return inference.MODEL_READY


__all__ = [
    "JobDataPipeline",
    "train_model",
    "calculate_match",
    "rank_jobs",
    "load_model",
    "is_model_ready",
]
