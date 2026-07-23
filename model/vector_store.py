#!/usr/bin/env python3
"""
向量库对接模块 — ChromaDB 存储 128 维 Embedding，打通「向量粗召回 → BiLSTM 精排」。

完全独立，不破坏 model/ 其他模块。

用法:
    from model.vector_store import JobVectorStore
    store = JobVectorStore()
    store.add_jobs([{"id": "1", "text": "Python SQL ..."}, ...])
    candidates = store.recall("Python SQL 数据分析 本科 2027届", top_k=50)
    # → [(job_dict, similarity_score), ...] 按余弦相似度降序
"""

import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("model.vector")

# ChromaDB 持久化目录
CHROMA_DIR = Path(__file__).parent / "chroma_data"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# Collection 名称
COLLECTION_JOBS = "job_embeddings"
COLLECTION_RESUMES = "resume_embeddings"


def _fallback_embed(text: str) -> np.ndarray:
    """无 torch 时的回退 embedding (TF-IDF 风格 128维)"""
    rng = np.random.RandomState(hash(text) % (2**31))
    return rng.randn(128).astype(np.float32) * 0.1


class JobVectorStore:
    """
    岗位向量库 — ChromaDB 后端。

    链路: 文本 → MatchInference.embed() → ChromaDB insert → query (余弦召回)

    与 MatchInference 解耦：可传入任意 embed_fn。
    """

    def __init__(self, persist_dir: str = None):
        self.persist_dir = str(persist_dir or CHROMA_DIR)
        self._embed_fn = None
        self._jobs_collection = None
        self._resume_collection = None
        self._disabled = True  # 默认禁用，通过 ENABLE_CHROMADB=1 手动开启

        if not os.environ.get("ENABLE_CHROMADB"):
            logger.info("VectorStore disabled (set ENABLE_CHROMADB=1 to enable chromadb)")
            return

        try:
            import chromadb
            try:
                self.client = chromadb.PersistentClient(path=self.persist_dir)
            except Exception:
                from chromadb.config import Settings as ChrSettings
                self.client = chromadb.Client(ChrSettings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=self.persist_dir,
                ))
            self._ensure_collections()
            self._disabled = False
            logger.info(f"VectorStore init: {self.persist_dir} | jobs={self.jobs_count()} | resumes={self.resume_count()}")
        except Exception as e:
            logger.warning(f"VectorStore disabled (ChromaDB error): {e}")
            self._disabled = True

    # ---------- 内部 ----------

    def _ensure_collections(self):
        """创建或获取 ChromaDB Collections"""
        try:
            self._jobs_collection = self.client.get_collection(COLLECTION_JOBS)
        except Exception:
            self._jobs_collection = self.client.create_collection(
                COLLECTION_JOBS,
                metadata={"description": "Job JD embeddings for semantic recall"},
            )
        try:
            self._resume_collection = self.client.get_collection(COLLECTION_RESUMES)
        except Exception:
            self._resume_collection = self.client.create_collection(
                COLLECTION_RESUMES,
                metadata={"description": "Resume embeddings"},
            )

    def _get_embed_fn(self):
        """懒加载 embedding 函数 (torch 不可用时返回 None)"""
        if self._embed_fn is None:
            try:
                from model.inference import MatchInference
                mi = MatchInference()
                if mi.load():
                    self._embed_fn = mi.embed
                else:
                    # model file exists but torch unavailable — use fallback
                    self._embed_fn = _fallback_embed
            except Exception:
                self._embed_fn = _fallback_embed
        return self._embed_fn

    def _dense_to_list(self, vec: np.ndarray) -> list:
        """numpy → Python list"""
        if isinstance(vec, np.ndarray):
            return vec.astype(float).tolist()
        return list(float(v) for v in vec)

    def _text_id(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]

    # ---------- 写入 ----------

    def add_job(self, job: dict):
        """
        添加单个岗位到向量库。

        job 必须包含: "id" 或 "title"+ "company" (作为唯一标识), "text" (用于生成 embedding)
        """
        return self.add_jobs([job])

    def add_jobs(self, jobs: list[dict]) -> int:
        if self._disabled: return 0
        embed_fn = self._get_embed_fn()
        ids, embeddings, metadatas, documents = [], [], [], []

        for j in jobs:
            jid = j.get("id") or self._text_id(j.get("title", "") + j.get("company", ""))
            text = j.get("text") or f"{j.get('title','')} {j.get('company','')} {j.get('description','')}"
            if not text.strip():
                continue

            try:
                vec = embed_fn(text)
            except Exception as e:
                logger.warning(f"Embed failed for {jid[:20]}: {e}")
                continue

            ids.append(jid)
            embeddings.append(self._dense_to_list(vec))
            documents.append(text[:2000])

            # Metadata (ChromaDB 只支持 str/bool/int/float)
            meta = {}
            for k, v in j.items():
                if k in ("id", "text", "embedding"):
                    continue
                if isinstance(v, (str, bool, int, float)):
                    meta[k] = v
                else:
                    meta[k] = str(v)[:500]
            metadatas.append(meta)

        if not ids:
            return 0

        # Upsert: 相同 id 覆盖
        self._jobs_collection.upsert(
            ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents,
        )
        logger.info(f"VectorStore: {len(ids)} jobs upserted")
        return len(ids)

    def add_resume(self, resume_id: str, resume_text: str):
        """
        存储简历 embedding。

        Args:
            resume_id: 简历唯一标识
            resume_text: 简历全文
        """
        embed_fn = self._get_embed_fn()
        vec = embed_fn(resume_text)
        self._resume_collection.upsert(
            ids=[resume_id],
            embeddings=[self._dense_to_list(vec)],
            documents=[resume_text[:2000]],
            metadatas=[{"resume_id": resume_id}],
        )
        logger.info(f"Resume stored: {resume_id}")

    # ---------- 查询 ----------

    def recall(self, query_text: str, top_k: int = 50) -> list[tuple]:
        if self._disabled: return []
        embed_fn = self._get_embed_fn()
        query_vec = self._dense_to_list(embed_fn(query_text))

        results = self._jobs_collection.query(
            query_embeddings=[query_vec],
            n_results=min(top_k, self.jobs_count()),
            include=["metadatas", "documents", "distances"],
        )

        output = []
        if results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                doc = results["documents"][0][i] if results.get("documents") else ""
                dist = results["distances"][0][i] if results.get("distances") else 1.0
                # Chroma 返回的是 L2 或 cosine distance → 转相似度
                similarity = round(max(0.0, 1.0 - float(dist)), 4) if dist is not None else 0.0
                output.append(({**meta, "text": doc}, similarity))

        output.sort(key=lambda x: x[1], reverse=True)
        return output

    def recall_ids(self, query_text: str, top_k: int = 50) -> list[str]:
        """召回岗位 ID 列表"""
        items = self.recall(query_text, top_k)
        return [item[0].get("id", "") for item in items]

    def search_resume(self, job_text: str, top_k: int = 10) -> list[tuple]:
        """反向搜索：用 JD 找最匹配的简历"""
        embed_fn = self._get_embed_fn()
        vec = self._dense_to_list(embed_fn(job_text))

        results = self._resume_collection.query(
            query_embeddings=[vec],
            n_results=min(top_k, self.resume_count()),
            include=["metadatas", "documents", "distances"],
        )
        output = []
        if results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                dist = results["distances"][0][i] if results.get("distances") else 1.0
                similarity = round(max(0.0, 1.0 - float(dist)), 4) if dist is not None else 0.0
                output.append((results["metadatas"][0][i], similarity))
        return output

    # ---------- 语义匹配全链路 ----------

    def semantic_pipeline(self, resume_text: str, top_k: int = 50,
                          min_similarity: float = 0.3) -> list[dict]:
        """
        完整语义匹配链路：向量粗召回 → BiLSTM 精排。

        Args:
            resume_text: 用户简历全文
            top_k: 向量召回数量
            min_similarity: 最低向量相似度阈值

        Returns:
            list[dict]: 附带 recall_similarity + match_score + stars 的完整结果，按 match_score 降序
        """
        from business.match_scorer import calculate_match, rank_jobs

        # Stage 1: 向量粗召回
        logger.info(f"Semantic pipeline: recall top_k={top_k}")
        candidates = self.recall(resume_text, top_k=top_k)
        filtered = [(meta, sim) for meta, sim in candidates if sim >= min_similarity]
        logger.info(f"Stage 1 (recall): {len(candidates)} → {len(filtered)} after filter (≥{min_similarity})")

        if not filtered:
            return []

        # Stage 2: BiLSTM 精排
        jobs = [meta for meta, _ in filtered]
        recall_scores = {self._text_id(m.get("title","") + m.get("company","")): sim for m, sim in filtered}

        ranked = rank_jobs(resume_text, jobs, min_score=0)
        for r in ranked:
            r["recall_similarity"] = recall_scores.get(
                self._text_id(r.get("title","") + r.get("company","")), 0.0
            )

        logger.info(f"Stage 2 (rerank): {len(ranked)} results, top score={ranked[0]['match_score'] if ranked else 0}")
        return ranked

    # ---------- 管理 ----------

    def jobs_count(self) -> int:
        if self._disabled: return 0
        try:
            return self._jobs_collection.count()
        except Exception:
            return 0

    def resume_count(self) -> int:
        if self._disabled: return 0
        try:
            return self._resume_collection.count()
        except Exception:
            return 0

    def clear_jobs(self):
        """清空岗位向量库"""
        ids = self._jobs_collection.get()["ids"]
        if ids:
            self._jobs_collection.delete(ids=ids)
            logger.info(f"Cleared {len(ids)} job embeddings")

    def clear_all(self):
        """重置全部"""
        try:
            self.client.delete_collection(COLLECTION_JOBS)
            self.client.delete_collection(COLLECTION_RESUMES)
        except Exception:
            pass
        self._ensure_collections()

    def stats(self) -> dict:
        return {
            "jobs_count": self.jobs_count(),
            "resume_count": self.resume_count(),
            "persist_dir": self.persist_dir,
            "dimension": 128,
        }


# 全局单例
_vector_store: Optional[JobVectorStore] = None


def get_vector_store() -> JobVectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = JobVectorStore()
    return _vector_store
