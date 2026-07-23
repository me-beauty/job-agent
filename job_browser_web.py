#!/usr/bin/env python3
"""
Job Browser Web API — Flask Blueprint (auth handled by web_server).

All /api/* routes are auth-protected by web_server.before_request.
Internal error handling + logging + DB persistence.
"""

import datetime
import json
import os
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from db import get_db
from utils.logger import get_logger
from utils.browser_anti_detect import chunk_tasks

ROOT = Path(__file__).parent
logger = get_logger("api")

api_bp = Blueprint("api", __name__, url_prefix="/api")

# 任务状态（简易内存存储）
_task_store: dict = {}
_task_lock = threading.Lock()

JOB_SITES_INFO = {
    "shixiseng": {"name": "实习僧", "url": "https://www.shixiseng.com"},
    "nowcoder": {"name": "牛客网", "url": "https://www.nowcoder.com/jobs"},
    "zhipin": {"name": "BOSS直聘", "url": "https://www.zhipin.com"},
    "guopin": {"name": "国聘网", "url": "https://www.iguopin.com"},
    "lagou": {"name": "拉勾网", "url": "https://www.lagou.com"},
}


def _check_auth():
    """检查请求是否带了有效 token（web_server before_request 也会检查，这里双重保险）"""
    token = os.environ.get("JOB_AGENT_TOKEN", "job-agent-demo-token")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided = auth_header[7:]
    else:
        provided = request.args.get("token", "")
    return provided == token


# ============================================================
# API 路由
# ============================================================

@api_bp.route("/status")
def api_status():
    try:
        return jsonify({"status": "ok", "service": "Job Agent Browser API", "version": "2.0.0",
                        "llm_provider": os.environ.get("JOB_AGENT_LLM", "claude"),
                        "active_tasks": len(_task_store),
                        "timestamp": datetime.datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"/api/status error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/sites")
def api_sites():
    """列出支持的招聘网站"""
    return jsonify({"sites": JOB_SITES_INFO})


@api_bp.route("/search", methods=["POST"])
def api_search():
    """
    搜索岗位（异步任务）
    POST JSON: {"keyword": "数据科学", "sites": ["shixiseng"], "city": "石家庄"}
    """
    data = request.get_json(silent=True) or {}
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "keyword 不能为空"}), 400

    sites = data.get("sites", ["shixiseng", "nowcoder"])
    city = data.get("city", "石家庄")
    llm = data.get("llm", os.environ.get("JOB_AGENT_LLM", "claude"))

    task_id = f"search_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    with _task_lock:
        _task_store[task_id] = {"status": "pending", "type": "search", "result": None}

    try:
        db = get_db()
        db.add_task(task_id, "search", "pending", {"keyword": keyword, "city": city})
    except Exception:
        pass  # DB may not be init yet

    def _run():
        try:
            from job_browser import search_jobs_sync
            results = search_jobs_sync(keyword, sites=sites, city=city, llm_provider=llm)
            with _task_lock:
                _task_store[task_id] = {"status": "done", "type": "search", "result": {"count": len(results), "jobs": results}}
            try:
                db = get_db()
                db.update_task(task_id, "done", {"count": len(results)})
                for j in results:
                    db.add_job({"source": "browser", "title": j.get("position", j.get("title", "")),
                                "company": j.get("company", ""), "location": j.get("location", ""),
                                "salary": j.get("salary", ""), "url": j.get("url", ""),
                                "keywords": j.get("search_keyword", keyword)})
            except Exception:
                pass
            logger.info(f"Search done: {task_id} -> {len(results)} jobs")
        except Exception as e:
            logger.error(f"Search failed: {task_id} — {e}", exc_info=True)
            with _task_lock:
                _task_store[task_id] = {"status": "error", "type": "search", "result": {"error": str(e)}}
            try:
                get_db().update_task(task_id, "error", error_msg=str(e))
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "status": "started",
                    "message": f"搜索已启动: '{keyword}'。通过 /api/task/{task_id} 查询进度"}), 202


@api_bp.route("/apply", methods=["POST"])
def api_apply():
    """
    自动投递（异步任务）
    POST JSON: {"url": "...", "resume_path": "...", "info": {...}}
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url 不能为空"}), 400

    # --- TF 匹配分数过滤（新增）---
    min_score = data.get("min_score", 70)
    match_score = data.get("match_score")
    if match_score is not None:
        try:
            match_score = float(match_score)
            if match_score < min_score:
                return jsonify({
                    "error": f"匹配分数 {match_score} 低于阈值 {min_score}，自动跳过投递",
                    "score": match_score,
                    "threshold": min_score,
                }), 400
        except (ValueError, TypeError):
            pass  # 无效分数，忽略过滤
    # --- 过滤结束 ---

    resume_path = data.get("resume_path")
    applicant_info = data.get("info", {})
    llm = data.get("llm", os.environ.get("JOB_AGENT_LLM", "claude"))

    task_id = f"apply_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    with _task_lock:
        _task_store[task_id] = {"status": "pending", "type": "apply", "result": None}

    def _run():
        try:
            from job_browser import JobBrowserAgent, run_async
            agent = JobBrowserAgent(llm_provider=llm)
            result = run_async(agent.apply_to_job(url, resume_path=resume_path, applicant_info=applicant_info))
            with _task_lock:
                _task_store[task_id] = {"status": "done", "type": "apply", "result": result}
            try:
                db = get_db()
                db.update_task(task_id, "done", result)
                db.add_apply_log({"job_url": url, "resume_path": resume_path or "",
                                  "match_score": match_score or 0,
                                  "status": "success" if result.get("success") else "failed",
                                  "error_msg": result.get("message", "")})
            except Exception:
                pass
            logger.info(f"Apply done: {task_id} -> {url}")
        except Exception as e:
            logger.error(f"Apply failed: {task_id} — {e}", exc_info=True)
            with _task_lock:
                _task_store[task_id] = {"status": "error", "type": "apply", "result": {"error": str(e)}}

    threading.Thread(target=_run, daemon=True).start()

    return jsonify({
        "task_id": task_id,
        "status": "started",
        "message": f"开始投递 {url}，可通过 /api/task/{task_id} 查询结果",
    }), 202


@api_bp.route("/scrape", methods=["POST"])
def api_scrape():
    """
    抓取导出 CSV（异步任务）
    POST JSON: {"url": "...", "output_name": "...", "max_items": 20}
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url 不能为空"}), 400

    output_name = data.get("output_name")
    max_items = data.get("max_items", 20)
    selectors = data.get("selectors")
    llm = data.get("llm", os.environ.get("JOB_AGENT_LLM", "claude"))

    task_id = f"scrape_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    with _task_lock:
        _task_store[task_id] = {"status": "pending", "type": "scrape", "result": None}

    def _run():
        try:
            from job_browser import scrape_to_csv_sync
            csv_path = scrape_to_csv_sync(url, output_path=None if not output_name else str(ROOT / f"{output_name}.csv"), llm_provider=llm)
            with _task_lock:
                _task_store[task_id] = {"status": "done", "type": "scrape", "result": {"csv_path": csv_path}}
            try:
                get_db().update_task(task_id, "done", {"csv_path": csv_path})
            except Exception:
                pass
            logger.info(f"Scrape done: {task_id} -> {csv_path}")
        except Exception as e:
            logger.error(f"Scrape failed: {task_id} — {e}", exc_info=True)
            with _task_lock:
                _task_store[task_id] = {"status": "error", "type": "scrape", "result": {"error": str(e)}}
            try:
                get_db().update_task(task_id, "error", error_msg=str(e))
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "status": "started",
                    "message": f"抓取已启动: {url}。通过 /api/task/{task_id} 查询进度"}), 202


@api_bp.route("/tasks", methods=["GET"])
def api_list_tasks():
    """List all tasks (DB-backed)"""
    try:
        db = get_db()
        tasks = db.list_tasks(limit=50)
        # Merge with in-memory tasks
        with _task_lock:
            for tid, t in _task_store.items():
                if not any(d.get("task_id") == tid for d in tasks):
                    tasks.insert(0, {"task_id": tid, "type": t.get("type", "?"), "status": t.get("status", "?"),
                                     "result": json.dumps(t.get("result", {}), ensure_ascii=False) if t.get("result") else "{}",
                                     "created_at": "", "updated_at": ""})
        return jsonify({"tasks": tasks, "count": len(tasks)})
    except Exception as e:
        logger.error(f"List tasks error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/task/<task_id>")
def api_task_status(task_id):
    """Query task status (in-memory + DB)"""
    with _task_lock:
        task = _task_store.get(task_id)
    if task is not None:
        return jsonify({"task_id": task_id, **task})

    # Check DB
    try:
        db = get_db()
        db_task = db.get_task(task_id)
        if db_task:
            return jsonify(db_task)
    except Exception:
        pass

    return jsonify({"error": "任务不存在"}), 404


@api_bp.route("/browser-check")
def api_browser_check():
    """检查浏览器环境（同步，无浏览器操作）"""
    checks = {}

    # browser-use
    try:
        import browser_use
        bu_version = getattr(browser_use, '__version__', 'installed')
        checks["browser_use"] = {"ok": True, "version": bu_version}
    except ImportError:
        checks["browser_use"] = {"ok": False, "message": "未安装 — pip install browser-use"}

    # playwright
    try:
        import playwright
        pw_version = getattr(playwright, '__version__', 'installed')
        checks["playwright"] = {"ok": True, "version": pw_version}
    except ImportError:
        checks["playwright"] = {"ok": False, "message": "未安装 — pip install playwright"}

    # API Keys
    checks["anthropic_key"] = {"ok": bool(os.environ.get("ANTHROPIC_API_KEY"))}
    checks["deepseek_key"] = {"ok": bool(os.environ.get("DEEPSEEK_API_KEY"))}

    return jsonify(checks)
