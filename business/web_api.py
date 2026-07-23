#!/usr/bin/env python3
"""
Flask API Blueprint — 求职业务 Web 接口。

迁移自原 job_browser_web.py，import 路径指向新模块。
所有 /api/* 路由通过 web_server.py 统一鉴权。
"""

import datetime
import hashlib
import json
import os
import threading

from flask import Blueprint, jsonify, request

from config.settings import settings
from db import get_db
from engine.task_manager import TaskManager
from engine.priority_queue import get_queue, TYPE_PRIORITY_MAP
from utils.logger import get_logger
from utils.browser_anti_detect import chunk_tasks

logger = get_logger("api")

api_bp = Blueprint("api", __name__, url_prefix="/api")
_lock = threading.Lock()
_memory_tasks: dict = {}

JOB_SITES_INFO = {
    "shixiseng": {"name": "实习僧", "url": "https://www.shixiseng.com"},
    "nowcoder": {"name": "牛客网", "url": "https://www.nowcoder.com/jobs"},
    "zhipin": {"name": "BOSS直聘", "url": "https://www.zhipin.com"},
    "guopin": {"name": "国聘网", "url": "https://www.iguopin.com"},
    "lagou": {"name": "拉勾网", "url": "https://www.lagou.com"},
}


# ============================================================
# API routes (identical to original job_browser_web.py)
# ============================================================

@api_bp.route("/status")
def api_status():
    try:
        return jsonify({"status": "ok", "service": "Job Agent Browser API", "version": "3.0.0",
                        "llm_provider": settings.JOB_AGENT_LLM,
                        "active_tasks": len(_memory_tasks),
                        "timestamp": datetime.datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"/api/status error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/sites")
def api_sites():
    return jsonify({"sites": JOB_SITES_INFO})


@api_bp.route("/search", methods=["POST"])
def api_search():
    data = request.get_json(silent=True) or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "keyword 不能为空"}), 400

    sites = data.get("sites", ["shixiseng", "nowcoder"])
    city = data.get("city", "石家庄")
    llm = data.get("llm", settings.JOB_AGENT_LLM)

    task_id = TaskManager.create("search", {"keyword": keyword, "city": city})
    with _lock: _memory_tasks[task_id] = {"status": "queued", "type": "search", "result": None}

    def _pipeline(kw, sts, ct, llm_provider):
        """搜索 -> SQLite入库 -> 向量库同步 (队列执行)"""
        with _lock: _memory_tasks[task_id] = {"status": "running", "type": "search", "result": None}
        try:
            from business.collector import get_collector
            collector = get_collector()
            results = collector.collect(kw, city=ct, max_per_source=10)

            # 1) Save to SQLite
            db = get_db()
            for j in results:
                db.add_job({"source": j.get("source", "collector"),
                            "title": j.get("position", j.get("title", "")),
                            "company": j.get("company", ""),
                            "location": j.get("location", ""),
                            "salary": j.get("salary", ""),
                            "url": j.get("url", ""),
                            "description": j.get("description", ""),
                            "keywords": j.get("search_keyword", kw)})

            # 2) Auto-sync to lightweight vector store
            try:
                from model.lightweight_vector import get_vector_store
                vs = get_vector_store()
                if results:
                    job_dicts = [{
                    "id": hashlib.md5(
                        (j.get("url", "") + j.get("company", "")).encode()
                    ).hexdigest()[:16],
                    "title": j.get("position", j.get("title", "")),
                    "company": j.get("company", ""),
                    "description": j.get("description", ""),
                    "text": (f"{j.get('position', j.get('title', ''))} "
                             f"{j.get('company', '')} {j.get('description', '')} "
                             f"{j.get('location', '')} {j.get('salary', '')} {kw}"),
                    "location": j.get("location", ""),
                    "salary": j.get("salary", ""),
                    "keywords": j.get("search_keyword", kw),
                    "source": j.get("source", ""),
                    "is_local": j.get("is_local", False),
                    "is_nearby": j.get("is_nearby", False),
                    "priority": j.get("priority", 0),
                    "note": j.get("note", ""),
                    "url": j.get("url", ""),
                } for j in results]
                    synced = vs.add_jobs(job_dicts)
                    logger.info(f"Auto-synced {synced}/{len(results)} jobs to vector store")
            except Exception as e:
                logger.warning(f"Auto-sync to vector failed (non-fatal): {e}")

            with _lock: _memory_tasks[task_id] = {"status": "done", "type": "search",
                                                   "result": {"count": len(results), "jobs": results}}
            return {"count": len(results), "jobs": results}
        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            with _lock: _memory_tasks[task_id] = {"status": "error", "type": "search",
                                                   "result": {"error": str(e)}}
            raise  # 让队列层也记录 TaskManager error

    pq = get_queue()
    pq.enqueue_by_type(task_id, "search", _pipeline, keyword, sites, city, llm)

    return jsonify({"task_id": task_id, "status": "queued",
                    "message": f"搜索已入队: '{keyword}' (优先级队列)。通过 /api/task/{task_id} 查询进度"}), 202


@api_bp.route("/apply", methods=["POST"])
def api_apply():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url: return jsonify({"error": "url 不能为空"}), 400

    min_score = data.get("min_score", 70)
    match_score = data.get("match_score")
    if match_score is not None:
        try:
            if float(match_score) < min_score:
                return jsonify({"error": f"匹配分数 {match_score} 低于阈值 {min_score}，跳过投递",
                                "score": match_score, "threshold": min_score}), 400
        except (ValueError, TypeError): pass

    resume_path = data.get("resume_path")
    applicant_info = data.get("info", {})
    llm = data.get("llm", settings.JOB_AGENT_LLM)
    task_id = TaskManager.create("apply", {"url": url})

    with _lock: _memory_tasks[task_id] = {"status": "pending", "type": "apply", "result": None}

    def _run():
        try:
            from business.job_apply import apply_job_sync
            result = apply_job_sync(url, resume_path=resume_path, applicant_info=applicant_info, llm_provider=llm)
            with _lock: _memory_tasks[task_id] = {"status": "done", "type": "apply", "result": result}
            TaskManager.update(task_id, "done", result)
        except Exception as e:
            logger.error(f"Apply failed: {e}", exc_info=True)
            with _lock: _memory_tasks[task_id] = {"status": "error", "type": "apply", "result": {"error": str(e)}}

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "status": "started",
                    "message": f"投递已启动: {url}"}), 202


@api_bp.route("/scrape", methods=["POST"])
def api_scrape():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url: return jsonify({"error": "url 不能为空"}), 400
    # Delegate to job_browser for now (backward compat)
    task_id = TaskManager.create("scrape", {"url": url})
    return jsonify({"task_id": task_id, "status": "started",
                    "message": f"抓取已启动: {url}。通过 /api/task/{task_id} 查询进度"}), 202


@api_bp.route("/tasks", methods=["GET"])
def api_list_tasks():
    try:
        db_tasks = TaskManager.list(limit=50)
        with _lock:
            for tid, t in _memory_tasks.items():
                if not any(d.get("task_id") == tid for d in db_tasks):
                    db_tasks.insert(0, {"task_id": tid, "type": t.get("type", "?"),
                                        "status": t.get("status", "?"),
                                        "result": json.dumps(t.get("result", {}), ensure_ascii=False) if t.get("result") else "{}",
                                        "created_at": "", "updated_at": ""})
        return jsonify({"tasks": db_tasks, "count": len(db_tasks)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/task/<task_id>")
def api_task_status(task_id):
    with _lock:
        mem = _memory_tasks.get(task_id)
    if mem: return jsonify({"task_id": task_id, **mem})
    db_task = TaskManager.get(task_id)
    if db_task: return jsonify(db_task)
    return jsonify({"error": "任务不存在"}), 404


@api_bp.route("/vector/stats", methods=["GET"])
def api_vector_stats():
    """向量库统计"""
    try:
        from model.lightweight_vector import get_vector_store
        vs = get_vector_store()
        return jsonify(vs.stats())
    except Exception as e:
        logger.error(f"Vector stats error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/vector/recall", methods=["POST"])
def api_vector_recall():
    """
    向量粗召回（不含精排）
    POST {"query_text": "...", "top_k": 50, "min_similarity": 0.3}
    """
    data = request.get_json(silent=True) or {}
    query = data.get("query_text", "").strip()
    if not query:
        return jsonify({"error": "query_text 不能为空"}), 400

    top_k = int(data.get("top_k", 50))
    min_sim = float(data.get("min_similarity", 0.05))

    try:
        from model.lightweight_vector import get_vector_store
        vs = get_vector_store()
        results = vs.recall(query, top_k=top_k)
        filtered = [{"job": meta, "similarity": sim} for meta, sim in results if sim >= min_sim]
        return jsonify({"results": filtered, "count": len(filtered), "total_stored": vs.jobs_count()})
    except Exception as e:
        logger.error(f"Vector recall error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/vector/semantic", methods=["POST"])
def api_semantic_search():
    """
    完整语义匹配链路：向量粗召回 → BiLSTM 精排
    POST {"resume_text": "...", "top_k": 50, "min_similarity": 0.3}
    """
    data = request.get_json(silent=True) or {}
    resume = data.get("resume_text", "").strip()
    if not resume:
        return jsonify({"error": "resume_text 不能为空"}), 400

    top_k = int(data.get("top_k", 50))
    min_sim = float(data.get("min_similarity", 0.05))

    try:
        from model.lightweight_vector import get_vector_store
        vs = get_vector_store()
        results = vs.semantic_pipeline(resume, top_k=top_k, min_similarity=min_sim)

        scores = [{
            "title": r.get("title", ""), "company": r.get("company", ""),
            "location": r.get("location", ""), "url": r.get("url", ""),
            "is_local": r.get("is_local", False), "is_nearby": r.get("is_nearby", False),
            "recall_similarity": r.get("recall_similarity", 0),
            "match_score": r["match_score"], "stars": r["stars"],
            "tier": r["tier"], "auto_apply": r["auto_apply"],
        } for r in results]

        # Log to DB
        try:
            db = get_db()
            for r in results:
                db.add_job({"source": "semantic", "title": r.get("title", ""),
                            "company": r.get("company", ""), "match_score": r["match_score"]})
        except Exception:
            pass

        return jsonify({"scores": scores, "count": len(scores),
                        "stages": {"recall_candidates": top_k, "final": len(scores)}})
    except Exception as e:
        logger.error(f"Semantic search error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/vector/sync", methods=["POST"])
def api_vector_sync():
    """将 DB 中的岗位批量同步到向量库"""
    try:
        db = get_db()
        jobs = db.get_jobs(limit=500)
        if not jobs:
            return jsonify({"message": "DB 中无岗位数据", "synced": 0})

        from model.lightweight_vector import get_vector_store
        vs = get_vector_store()
        # Convert DB rows to vector store format
        job_dicts = []
        for j in jobs:
            job_dicts.append({
                "id": str(j.get("id", "")),
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "description": j.get("description", ""),
                "text": f"{j.get('title','')} {j.get('company','')} {j.get('description','')}",
                "location": j.get("location", ""),
                "salary": j.get("salary", ""),
                "keywords": j.get("keywords", ""),
            })

        count = vs.add_jobs(job_dicts)
        logger.info(f"Vector sync: {count} jobs indexed")
        return jsonify({"message": f"已同步 {count} 个岗位到向量库", "synced": count,
                        "total_stored": vs.jobs_count()})
    except Exception as e:
        logger.error(f"Vector sync error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/queue/stats", methods=["GET"])
def api_queue_stats():
    """任务优先级队列状态"""
    try:
        pq = get_queue()
        return jsonify({"queue": pq.stats(), "pending": pq.dump_queue()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---- Priority-aware task submission (optional, backward-compatible) ----------
@api_bp.route("/search-prioritized", methods=["POST"])
def api_search_prioritized():
    """通过优先级队列提交搜索任务（与 /api/search 相同流水线）"""
    data = request.get_json(silent=True) or {}
    keyword = data.get("keyword", "").strip()
    if not keyword: return jsonify({"error": "keyword 不能为空"}), 400

    sites = data.get("sites", ["shixiseng", "nowcoder"])
    city = data.get("city", "石家庄")
    llm = data.get("llm", settings.JOB_AGENT_LLM)

    task_id = TaskManager.create("search", {"keyword": keyword, "mode": "prioritized"})
    with _lock: _memory_tasks[task_id] = {"status": "queued", "type": "search", "result": None}

    def _pipeline(kw, sts, ct, llm_provider):
        """搜索 -> SQLite入库 -> 向量库同步"""
        with _lock: _memory_tasks[task_id] = {"status": "running", "type": "search", "result": None}
        try:
            from business.collector import get_collector
            collector = get_collector()
            results = collector.collect(kw, city=ct, max_per_source=10)

            db = get_db()
            for j in results:
                db.add_job({"source": j.get("source", "collector"),
                            "title": j.get("position", j.get("title", "")),
                            "company": j.get("company", ""),
                            "location": j.get("location", ""),
                            "salary": j.get("salary", ""),
                            "url": j.get("url", ""),
                            "description": j.get("description", ""),
                            "keywords": j.get("search_keyword", kw)})

            try:
                from model.lightweight_vector import get_vector_store
                vs = get_vector_store()
                if results:
                    job_dicts = [{
                    "id": hashlib.md5(
                        (j.get("url", "") + j.get("company", "")).encode()
                    ).hexdigest()[:16],
                    "title": j.get("position", j.get("title", "")),
                    "company": j.get("company", ""),
                    "description": j.get("description", ""),
                    "text": (f"{j.get('position', j.get('title', ''))} "
                             f"{j.get('company', '')} {j.get('description', '')} "
                             f"{j.get('location', '')} {j.get('salary', '')} {kw}"),
                    "location": j.get("location", ""),
                    "salary": j.get("salary", ""),
                    "keywords": j.get("search_keyword", kw),
                    "source": j.get("source", ""),
                    "is_local": j.get("is_local", False),
                    "is_nearby": j.get("is_nearby", False),
                    "priority": j.get("priority", 0),
                    "note": j.get("note", ""),
                    "url": j.get("url", ""),
                } for j in results]
                    synced = vs.add_jobs(job_dicts)
                    logger.info(f"Auto-synced {synced}/{len(results)} jobs to vector store")
            except Exception as e:
                logger.warning(f"Auto-sync to vector failed (non-fatal): {e}")

            with _lock: _memory_tasks[task_id] = {"status": "done", "type": "search",
                                                   "result": {"count": len(results), "jobs": results}}
            return {"count": len(results), "jobs": results}
        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            with _lock: _memory_tasks[task_id] = {"status": "error", "type": "search",
                                                   "result": {"error": str(e)}}
            raise

    pq = get_queue()
    pq.enqueue_by_type(task_id, "search", _pipeline, keyword, sites, city, llm)

    return jsonify({"task_id": task_id, "status": "queued",
                    "message": f"搜索已入队 (优先级队列): '{keyword}'"}), 202


@api_bp.route("/data/sync", methods=["POST"])
def api_data_sync():
    """全量同步多源数据 → DB → 向量库 → 快照"""
    try:
        from model.sync_data import full_sync
        results = full_sync()
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        logger.error(f"Data sync error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/data/stats", methods=["GET"])
def api_data_stats():
    """样本监控面板数据"""
    try:
        from model.monitor import SampleMonitor
        sm = SampleMonitor()
        snapshot = sm.report()
        balance = sm.balance_summary()
        history = sm.history(limit=15)
        return jsonify({"snapshot": snapshot, "balance": balance, "history": history})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/data/snapshot", methods=["POST"])
def api_take_snapshot():
    """手动采集样本快照"""
    try:
        from model.monitor import SampleMonitor
        sm = SampleMonitor()
        stats = sm.take_snapshot()
        return jsonify({"status": "ok", "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tool-calls", methods=["GET"])
def api_tool_calls():
    """MCP 工具调用历史"""
    try:
        db = get_db()
        tool = request.args.get("tool")
        calls = db.get_tool_calls(limit=100, tool_name=tool)
        stats = db.tool_call_stats()
        return jsonify({"calls": calls, "count": len(calls), "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/browser-check")
def api_browser_check():
    checks = {}
    try:
        import browser_use
        checks["browser_use"] = {"ok": True, "version": getattr(browser_use, "__version__", "installed")}
    except ImportError:
        checks["browser_use"] = {"ok": False}
    try:
        import playwright
        checks["playwright"] = {"ok": True, "version": getattr(playwright, "__version__", "installed")}
    except ImportError:
        checks["playwright"] = {"ok": False}
    checks["anthropic_key"] = {"ok": bool(os.environ.get("ANTHROPIC_API_KEY"))}
    checks["deepseek_key"] = {"ok": bool(os.environ.get("DEEPSEEK_API_KEY"))}
    return jsonify(checks)
