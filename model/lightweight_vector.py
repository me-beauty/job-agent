#!/usr/bin/env python3
"""
轻量向量库 — 纯 numpy 实现，零 C 扩展依赖。
自动检测模型 embedding 维度，模型不可用时回退到关键词 embedding。
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("model.vector")

VECTOR_DIR = Path(__file__).parent / "vector_data"
VECTOR_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDINGS_FILE = VECTOR_DIR / "embeddings.npy"
METADATA_FILE = VECTOR_DIR / "metadata.json"

_KEYWORD_VOCAB = [
    "python", "sql", "数据分析", "数据科学", "机器学习", "深度学习",
    "pandas", "numpy", "spark", "hadoop", "tensorflow", "pytorch",
    "数据挖掘", "数据可视化", "excel", "tableau", "powerbi",
    "java", "scala", "r语言", "统计学", "数学", "算法",
    "大数据", "数据仓库", "etl", "数据工程", "数据治理",
    "实习", "应届", "2027届", "本科", "硕士",
    "石家庄", "保定", "唐山", "北京", "天津", "廊坊", "雄安", "河北",
]


def _get_embed_dim() -> int:
    """Get embedding dimension from loaded model, or use keyword-based dim"""
    try:
        from model.inference import MatchInference
        mi = MatchInference()
        if mi.load():
            vec = mi.embed("test dim check")
            dim = vec.shape[0]
            return dim
    except Exception:
        pass
    return max(len(_KEYWORD_VOCAB), 64)


def _hash_embed(text: str) -> np.ndarray:
    """Keyword + hash embedding"""
    dim = _get_embed_dim()
    text_lower = text.lower()
    vec = np.zeros(dim, dtype=np.float32)
    for i, kw in enumerate(_KEYWORD_VOCAB):
        if i >= dim:
            break
        if kw in text_lower:
            vec[i] = 1.0
    n_kw = min(len(_KEYWORD_VOCAB), dim)
    if n_kw < dim:
        seed = hash(text) % (2**31)
        rng = np.random.RandomState(seed)
        vec[n_kw:] = rng.randn(dim - n_kw).astype(np.float32) * 0.01
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def _try_model_embed(text: str) -> Optional[np.ndarray]:
    """Try using BiLSTM model, return None if unavailable"""
    try:
        from model.inference import MatchInference
        mi = MatchInference()
        if mi.load():
            vec = mi.embed(text)
            if isinstance(vec, np.ndarray):
                return vec.astype(np.float32)
    except Exception:
        pass
    return None


def embed_text(text: str) -> np.ndarray:
    """Generate embedding: model first, keyword fallback"""
    vec = _try_model_embed(text)
    if vec is not None:
        return vec
    return _hash_embed(text)


class LightweightVectorStore:
    """轻量向量库 — numpy + JSON，自动适配模型维度"""

    def __init__(self):
        self._embeddings: Optional[np.ndarray] = None
        self._metadata: list[dict] = []
        self._ids: list[str] = []
        self._dirty = False
        self._embed_dim: int = 0
        self._load()

    def _load(self):
        """Load from disk, clear if dimension mismatch"""
        if EMBEDDINGS_FILE.exists() and METADATA_FILE.exists():
            try:
                saved = np.load(str(EMBEDDINGS_FILE))
                with open(METADATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._metadata = data.get("metadata", [])
                self._ids = data.get("ids", [])

                current_dim = _get_embed_dim()
                if saved.shape[0] > 0 and saved.shape[1] != current_dim:
                    # Dimension mismatch — old data from different model, discard
                    logger.warning(
                        f"Vector dim mismatch: saved={saved.shape[1]} current={current_dim}. "
                        f"Clearing old data."
                    )
                    self._embeddings = np.empty((0, current_dim), dtype=np.float32)
                    self._metadata = []
                    self._ids = []
                    self._dirty = True
                    self._save()
                    return

                self._embeddings = saved
                self._embed_dim = saved.shape[1] if saved.shape[0] > 0 else _get_embed_dim()
                logger.info(f"VectorStore loaded: {len(self._ids)} jobs, dim={self._embed_dim}")
                return
            except Exception as e:
                logger.warning(f"Failed to load vectors: {e}")

        dim = _get_embed_dim()
        self._embeddings = np.empty((0, dim), dtype=np.float32)
        self._metadata = []
        self._ids = []

    def _save(self):
        try:
            np.save(str(EMBEDDINGS_FILE), self._embeddings)
            with open(METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump({"ids": self._ids, "metadata": self._metadata}, f, ensure_ascii=False)
            self._dirty = False
        except Exception as e:
            logger.warning(f"Failed to save vectors: {e}")

    def add_job(self, job: dict) -> int:
        return self.add_jobs([job])

    def add_jobs(self, jobs: list[dict]) -> int:
        if not jobs:
            return 0

        dim = _get_embed_dim()
        new_embs = []
        for j in jobs:
            jid = j.get("id") or hashlib.md5(
                (j.get("title", "") + j.get("company", "")).encode()
            ).hexdigest()[:16]
            text = j.get("text") or f"{j.get('title','')} {j.get('company','')} {j.get('description','')}"
            if not text.strip():
                continue

            vec = embed_text(text)

            if jid in self._ids:
                idx = self._ids.index(jid)
                self._embeddings[idx] = vec
                self._metadata[idx] = {k: v for k, v in j.items() if k not in ("text", "embedding")}
            else:
                self._ids.append(jid)
                new_embs.append(vec)
                self._metadata.append({k: v for k, v in j.items() if k not in ("text", "embedding")})

        if new_embs:
            if len(self._embeddings) == 0 or self._embeddings.shape[0] == 0:
                self._embeddings = np.array(new_embs, dtype=np.float32)
            else:
                self._embeddings = np.vstack([self._embeddings, np.array(new_embs, dtype=np.float32)])

        self._dirty = True
        self._save()
        logger.info(f"VectorStore: {len(jobs)} jobs added (total={len(self._ids)})")
        return len(jobs)

    def recall(self, query_text: str, top_k: int = 50) -> list[tuple]:
        if self._embeddings is None or len(self._embeddings) == 0:
            return []

        query_vec = embed_text(query_text)
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return []

        db_norms = np.linalg.norm(self._embeddings, axis=1)
        dots = np.dot(self._embeddings, query_vec)
        denom = db_norms * q_norm
        denom[denom == 0] = 1.0
        similarities = dots / denom

        k = min(top_k, len(similarities))
        if k == 0:
            return []

        top_indices = np.argsort(similarities)[::-1][:k]
        results = []
        for idx in top_indices:
            sim = float(similarities[idx])
            meta = dict(self._metadata[idx])
            meta["id"] = self._ids[idx]
            results.append((meta, round(sim, 4)))
        return results

    def recall_ids(self, query_text: str, top_k: int = 50) -> list[str]:
        return [item[0].get("id", "") for item in self.recall(query_text, top_k)]

    def semantic_pipeline(self, resume_text: str, top_k: int = 50,
                          min_similarity: float = 0.05) -> list[dict]:
        from business.match_scorer import rank_jobs

        candidates = self.recall(resume_text, top_k=top_k)
        filtered = [(meta, sim) for meta, sim in candidates if sim >= min_similarity]
        logger.info(f"Stage 1 (recall): {len(candidates)} -> {len(filtered)} (>={min_similarity})")

        if not filtered:
            return []

        jobs = [meta for meta, _ in filtered]
        ranked = rank_jobs(resume_text, jobs, min_score=0)

        # Attach recall similarity
        recall_map = {
            meta.get("id", hashlib.md5(
                (meta.get("title", "") + meta.get("company", "")).encode()
            ).hexdigest()[:16]): sim
            for meta, sim in filtered
        }
        for r in ranked:
            rid = r.get("id") or hashlib.md5(
                (r.get("title", "") + r.get("company", "")).encode()
            ).hexdigest()[:16]
            r["recall_similarity"] = recall_map.get(rid, 0.0)

        logger.info(f"Stage 2 (rerank): {len(ranked)} results")
        return ranked

    def jobs_count(self) -> int:
        return len(self._ids)

    def resume_count(self) -> int:
        return 0

    def clear_jobs(self):
        dim = _get_embed_dim()
        self._embeddings = np.empty((0, dim), dtype=np.float32)
        self._metadata = []
        self._ids = []
        self._dirty = True
        self._save()

    def stats(self) -> dict:
        return {
            "jobs_count": self.jobs_count(),
            "resume_count": self.resume_count(),
            "persist_dir": str(VECTOR_DIR),
            "dimension": self._embeddings.shape[1] if self._embeddings is not None and self._embeddings.shape[0] > 0 else _get_embed_dim(),
        }


_vector_store: Optional[LightweightVectorStore] = None


def get_vector_store() -> LightweightVectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = LightweightVectorStore()
    return _vector_store
