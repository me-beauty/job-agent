#!/usr/bin/env python3
"""
推理模块 — PyTorch 人岗匹配打分

核心函数：
  calculate_match(resume_text, job_text) → float
  rank_jobs(resume_text, jobs_list) → list[dict]
  load_model() → (MatchModel, vocab_info) or None
"""

import os
import sys
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).parent / "model_storage"

_model_cache = None
_vocab_info = None
MODEL_READY = False

RESUME_FEATURE_KW = [
    "Python", "SQL", "数据分析", "机器学习", "Pandas", "NumPy",
    "Spark", "Hadoop", "TensorFlow", "PyTorch", "Scikit-learn",
    "Tableau", "PowerBI", "数据可视化", "Excel", "统计",
    "深度学习", "NLP", "计算机视觉", "数学建模",
]


def load_model(model_path: str = None):
    """加载 PyTorch 模型"""
    global _model_cache, _vocab_info, MODEL_READY

    try:
        import torch
    except ImportError:
        print("[WARN] PyTorch not installed")
        return None

    from .train import MatchModel
    from .data_pipeline import text_to_ids

    if model_path is None:
        pt_files = sorted(MODEL_DIR.glob("*.pt"), key=os.path.getmtime, reverse=True)
        if not pt_files:
            print("[WARN] No .pt model found, using fallback scoring")
            return None
        model_path = str(pt_files[0])

    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    vocab_size = ckpt["vocab_size"]
    max_len = ckpt.get("max_len", 512)

    model = MatchModel(vocab_size, max_len=max_len)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    _model_cache = model
    _vocab_info = {"vocab_size": vocab_size, "max_len": max_len}
    MODEL_READY = True
    print(f"  Model loaded: {Path(model_path).name}")
    return model


def predict_single(resume_text: str, job_text: str) -> float:
    """单条打分 0-100"""
    if not MODEL_READY:
        load_model()
    if not MODEL_READY:
        return _fallback_score(resume_text, job_text)

    try:
        import torch
        from .data_pipeline import text_to_ids

        max_len = _vocab_info["max_len"]
        r_ids = text_to_ids(resume_text, max_len)
        j_ids = text_to_ids(job_text, max_len)

        r_t = torch.tensor([r_ids], dtype=torch.long)
        j_t = torch.tensor([j_ids], dtype=torch.long)
        # Pad if needed
        if r_t.shape[1] < max_len:
            r_t = torch.nn.functional.pad(r_t, (0, max_len - r_t.shape[1]))
        if j_t.shape[1] < max_len:
            j_t = torch.nn.functional.pad(j_t, (0, max_len - j_t.shape[1]))

        with torch.no_grad():
            score = _model_cache.forward(r_t, j_t, torch.device("cpu"))
        return round(float(score.item()) * 100, 1)
    except Exception as e:
        print(f"[WARN] Predict error: {e}")
        return _fallback_score(resume_text, job_text)


def _fallback_score(resume_text: str, job_text: str) -> float:
    """规则回退"""
    rl = resume_text.lower()
    jl = job_text.lower()
    hits = sum(1 for kw in RESUME_FEATURE_KW if kw in jl and kw in rl)
    loc_hit = any(loc in jl for loc in ["石家庄","保定","唐山","雄安","北京","天津","河北","廊坊"])
    return round(float(min(95, hits * 8 + (10 if loc_hit else 0) + 10)), 1)


def calculate_match(resume_text: str, job_text_or_id: str) -> float:
    return predict_single(resume_text, job_text_or_id)


def score_to_stars(score: float) -> str:
    if score >= 90: return "★★★★★"
    if score >= 80: return "★★★★☆"
    if score >= 70: return "★★★☆☆"
    if score >= 60: return "★★☆☆☆"
    return "★☆☆☆☆"


def score_tier(score: float) -> str:
    if score >= 85: return "S"
    if score >= 75: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    return "D"


def rank_jobs(resume_text: str, jobs: list[dict], min_score: float = 0) -> list[dict]:
    """批量打分排序"""
    results = []
    for job in jobs:
        title = job.get("title","")
        company = job.get("company","")
        desc = job.get("description") or job.get("text") or job.get("desc","")
        jt = f"{title} {company} {desc}"
        score = calculate_match(resume_text, jt)
        if score >= min_score:
            results.append({**job, "match_score": score, "stars": score_to_stars(score),
                            "tier": score_tier(score), "auto_apply": score >= 70})

    # Smart fallback: if model lacks variance, use rule-based
    if results and max(r["match_score"] for r in results) - min(r["match_score"] for r in results) < 3:
        for r in results:
            r["match_score"] = _fallback_score(resume_text, f"{r.get('title','')} {r.get('company','')} {r.get('description','')}")
            r["stars"] = score_to_stars(r["match_score"])
            r["tier"] = score_tier(r["match_score"])
            r["auto_apply"] = r["match_score"] >= 70

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return results


# Test
if __name__ == "__main__":
    resume = "Python SQL ML sklearn data science bachelor 2027 Beijing Shijiazhuang"
    jobs = [
        {"title":"Data Analyst","company":"Bytedance","description":"Python SQL data viz Beijing"},
        {"title":"Big Data","company":"Huawei","description":"Hadoop Spark Shenzhen"},
        {"title":"Sales","company":"Insurance","description":"sales customers"},
    ]
    results = rank_jobs(resume, jobs)
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r['company']} {r['title']}: {r['match_score']} {r['stars']} auto={r['auto_apply']}")
