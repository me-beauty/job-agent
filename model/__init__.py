#!/usr/bin/env python3
"""
model/ — 暂时跳过 torch 依赖 (DEBUG MODE)
除 inference 规则回退和向量库外，所有 torch 模块不加载。
"""

# inference: lazy import, torch optional
from .inference import MatchInference, text_to_ids, MODEL_READY, _fallback_score
# DataPipeline — no longer eagerly imported (fixes training endpoint)
from .data_pipeline import DataPipeline
# vector_store: chromadb segfault on 3.11, replaced by lightweight_vector
from .lightweight_vector import LightweightVectorStore as JobVectorStore, get_vector_store
from .monitor import SampleMonitor
from .sync_data import full_sync
from . import evaluation

# match_net / trainer — disabled
MatchModel = None
MatchTrainer = None

__all__ = [
    "MatchInference", "text_to_ids", "MODEL_READY", "_fallback_score",
    "DataPipeline", "JobVectorStore", "get_vector_store",
    "SampleMonitor", "full_sync", "evaluation",
]
