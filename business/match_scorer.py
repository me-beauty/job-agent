#!/usr/bin/env python3
"""
人岗匹配打分 — 求职业务插件，封装 model inference。

提供带业务规则的回退打分 + 模型打分。
所有 model 依赖均为懒加载，不阻塞 Flask 蓝图启动。
"""

_inference = None
_fallback = None


def _get_inference():
    global _inference
    if _inference is None:
        try:
            from model.inference import MatchInference
            _inference = MatchInference()
        except ImportError:
            return None
    return _inference

def _get_fallback():
    global _fallback
    if _fallback is None:
        try:
            from model.inference import _fallback_score
            _fallback = _fallback_score
        except ImportError:
            _fallback = _rule_score
    return _fallback

def _rule_score(text_a: str, text_b: str) -> float:
    """纯规则回退（无 PyTorch 依赖）"""
    kw = ["python","sql","数据分析","机器学习","pandas","spark","hadoop","tensorflow","pytorch","数据可视化","excel",
          "深度学习","nlp","计算机视觉","数学建模","django","flask","java","scala","数据挖掘","etl","数据仓库","linux","git","docker"]
    a,b = text_a.lower(), text_b.lower()
    hits = sum(1 for k in kw if k in b and k in a)

    # 地点加分
    loc_score = 0
    target_city = None
    for city in ["石家庄","保定","唐山","北京","天津","廊坊","雄安"]:
        if city in a:
            target_city = city
            break
    if target_city:
        if target_city in b:
            loc_score += 15  # 同城优先
        elif target_city in ["石家庄","保定","唐山","廊坊"] and any(c in b for c in ["北京","天津"]):
            loc_score += 8   # 河北→京津也算近

    # 大厂加分（企业名称在岗位文本中）
    top_tier = ["字节跳动","腾讯","阿里巴巴","蚂蚁集团","华为","百度","京东","美团","快手","网易","滴滴","小米","小红书","哔哩哔哩","拼多多","商汤科技","科大讯飞","旷视科技","携程","知乎"]
    mid_tier = ["石药集团","以岭药业","长城汽车","河钢集团","新奥集团","中科曙光","天地伟业","天地伟业"]
    for t in top_tier:
        if t in b:
            loc_score += 5
            break
    else:
        for t in mid_tier:
            if t in b:
                loc_score += 3
                break

    base = hits * 7 + loc_score + 10
    # 如果岗位在目标城市，给一个基础分兜底
    if target_city and target_city in b:
        base = max(base, 35)
    return round(float(min(92, base)), 1)


def calculate_match(resume_text: str, job_text: str) -> float:
    """单条匹配打分 0-100"""
    mi = _get_inference()
    if mi is not None:
        try: return mi.score(resume_text, job_text)
        except: pass
    return _get_fallback()(resume_text, job_text)


def export_embedding(text: str):
    """导出简历/岗位文本的 Embedding 向量"""
    mi = _get_inference()
    if mi is not None:
        return mi.embed(text)
    import numpy as np
    return np.zeros(128, dtype=np.float32)


def rank_jobs(resume_text: str, jobs: list[dict], min_score: float = 0) -> list[dict]:
    """批量打分排序，返回带 match_score/stars/tier/auto_apply 的结果"""
    results = []
    for job in jobs:
        title = job.get("title", ""); company = job.get("company", "")
        desc = job.get("description") or job.get("text") or job.get("desc", "")
        jt = f"{title} {company} {desc}"
        score = calculate_match(resume_text, jt)
        if score >= min_score:
            results.append({**job, "match_score": score,
                            "stars": _stars(score), "tier": _tier(score),
                            "auto_apply": score >= 70})

    # Smart fallback: only when model has NO weights loaded and scores lack variance
    mi = _get_inference()
    model_has_weights = mi is not None and getattr(mi, 'model', None) is not None
    if results and not model_has_weights and max(r["match_score"] for r in results) - min(r["match_score"] for r in results) < 3:
        for r in results:
            fb = _get_fallback()(resume_text, f"{r.get('title','')} {r.get('company','')} {r.get('description','')}")
            r["match_score"] = fb; r["stars"] = _stars(fb)
            r["tier"] = _tier(fb); r["auto_apply"] = fb >= 70

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return results


def is_model_ready() -> bool:
    try:
        from model.inference import MODEL_READY
        return MODEL_READY
    except ImportError:
        return False


def _stars(score: float) -> str:
    if score >= 90: return "★★★★★"
    if score >= 80: return "★★★★☆"
    if score >= 70: return "★★★☆☆"
    if score >= 60: return "★★☆☆☆"
    return "★☆☆☆☆"


def _tier(score: float) -> str:
    if score >= 85: return "S"
    if score >= 75: return "A"
    if score >= 65: return "B"
    if score >= 50: return "C"
    return "D"
