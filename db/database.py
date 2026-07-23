#!/usr/bin/env python3
"""
SQLite 数据库操作类 — 岗位/任务/投递记录/模型版本 持久化 CRUD。

Usage:
  from db import init_db, get_db
  init_db()
  db = get_db()
  db.add_job({"title":"数据分析实习","company":"字节跳动"})
  db.add_task("search_001","search","pending")
  db.update_task("search_001","done",'{"count":5}')
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "db" / "job_agent.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"

_lock = threading.Lock()
_conn_pool = None


def _get_conn() -> sqlite3.Connection:
    global _conn_pool
    if _conn_pool is None:
        _conn_pool = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn_pool.row_factory = sqlite3.Row
        _conn_pool.execute("PRAGMA journal_mode=WAL")
        _conn_pool.execute("PRAGMA foreign_keys=ON")
    return _conn_pool


def init_db():
    """初始化数据库表结构"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with _lock:
        conn.executescript(schema)
        conn.commit()
    print(f"[DB] Initialized: {DB_PATH}")


class JobDB:
    """岗位/任务/投递/模型 CRUD 操作类"""

    def _exec(self, sql: str, params: tuple = (), fetch: bool = False):
        conn = _get_conn()
        with _lock:
            cur = conn.execute(sql, params)
            if fetch:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            conn.commit()
            return cur

    # ==================== jobs ====================

    def add_job(self, job: dict) -> int:
        """添加岗位，返回 row id"""
        cur = self._exec(
            """INSERT INTO jobs (source,title,company,description,location,salary,url,keywords,match_score)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (job.get("source", "unknown"),
             job.get("title", ""),
             job.get("company", ""),
             job.get("description", ""),
             job.get("location", ""),
             job.get("salary", ""),
             job.get("url", ""),
             job.get("keywords", ""),
             job.get("match_score", 0)),
        )
        return cur.lastrowid

    def get_jobs(self, limit: int = 100, source: str = None, min_score: float = 0) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE match_score >= ?"
        params = [min_score]
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += " ORDER BY match_score DESC, created_at DESC LIMIT ?"
        params.append(limit)
        return self._exec(sql, tuple(params), fetch=True)

    def update_job_score(self, job_id: int, score: float):
        self._exec("UPDATE jobs SET match_score = ? WHERE id = ?", (score, job_id))

    def job_count(self, source: str = None) -> int:
        if source:
            rows = self._exec("SELECT COUNT(*) as c FROM jobs WHERE source = ?", (source,), fetch=True)
        else:
            rows = self._exec("SELECT COUNT(*) as c FROM jobs", fetch=True)
        return rows[0]["c"] if rows else 0

    def today_job_count(self) -> int:
        rows = self._exec(
            "SELECT COUNT(*) as c FROM jobs WHERE date(created_at) = date('now','localtime')",
            fetch=True,
        )
        return rows[0]["c"] if rows else 0

    # ==================== tasks ====================

    def add_task(self, task_id: str, task_type: str, status: str = "pending", params: dict = None) -> int:
        return self._exec(
            """INSERT INTO tasks (task_id,type,status,params) VALUES (?,?,?,?)""",
            (task_id, task_type, status, json.dumps(params or {}, ensure_ascii=False)),
        ).lastrowid

    def update_task(self, task_id: str, status: str, result: dict = None, error_msg: str = ""):
        self._exec(
            """UPDATE tasks SET status=?, result=?, error_msg=?, updated_at=datetime('now','localtime')
               WHERE task_id=?""",
            (status, json.dumps(result or {}, ensure_ascii=False), error_msg, task_id),
        )

    def get_task(self, task_id: str) -> Optional[dict]:
        rows = self._exec("SELECT * FROM tasks WHERE task_id = ?", (task_id,), fetch=True)
        if not rows:
            return None
        row = rows[0]
        try:
            row["params"] = json.loads(row["params"])
        except Exception:
            pass
        try:
            row["result"] = json.loads(row["result"])
        except Exception:
            pass
        return row

    def list_tasks(self, limit: int = 50) -> list[dict]:
        return self._exec(
            "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,), fetch=True,
        )

    # ==================== apply_logs ====================

    def add_apply_log(self, log: dict) -> int:
        return self._exec(
            """INSERT INTO apply_logs (job_id,job_url,resume_path,match_score,status,error_msg)
               VALUES (?,?,?,?,?,?)""",
            (log.get("job_id", 0),
             log.get("job_url", ""),
             log.get("resume_path", ""),
             log.get("match_score", 0),
             log.get("status", "skipped"),
             log.get("error_msg", "")),
        ).lastrowid

    def get_apply_logs(self, limit: int = 50) -> list[dict]:
        return self._exec(
            "SELECT * FROM apply_logs ORDER BY created_at DESC LIMIT ?", (limit,), fetch=True,
        )

    # ==================== models ====================

    def add_model(self, model: dict) -> int:
        return self._exec(
            """INSERT INTO models (name,path,epochs,val_mae,val_loss,accuracy,is_active,eval_report)
               VALUES (?,?,?,?,?,?,?,?)""",
            (model["name"],
             model["path"],
             model.get("epochs", 0),
             model.get("val_mae", 0),
             model.get("val_loss", 0),
             model.get("accuracy", 0),
             model.get("is_active", 0),
             model.get("eval_report", "")),
        ).lastrowid

    def list_models(self) -> list[dict]:
        return self._exec(
            "SELECT * FROM models ORDER BY created_at DESC", fetch=True,
        )

    def get_active_model(self) -> Optional[dict]:
        rows = self._exec("SELECT * FROM models WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1", fetch=True)
        return rows[0] if rows else None

    def set_active_model(self, name: str):
        self._exec("UPDATE models SET is_active = 0")
        self._exec("UPDATE models SET is_active = 1 WHERE name = ?", (name,))

    def prune_inactive_models(self, keep: int = 5):
        """仅保留最新 N 个模型 + 当前激活模型，删除其余"""
        active = self.get_active_model()
        all_models = self._exec("SELECT * FROM models ORDER BY created_at DESC", fetch=True)
        to_delete = []
        for i, m in enumerate(all_models):
            if i >= keep and (not active or m["name"] != active["name"]):
                to_delete.append(m)
        for m in to_delete:
            self._exec("DELETE FROM models WHERE id = ?", (m["id"],))
        return len(to_delete)

    def get_model_count(self) -> int:
        rows = self._exec("SELECT COUNT(*) as c FROM models", fetch=True)
        return rows[0]["c"] if rows else 0

    # ==================== tool_calls (v3.1) ====================

    def log_tool_call(self, call: dict) -> int:
        return self._exec(
            """INSERT OR REPLACE INTO tool_calls (call_id,tool_name,params,result,duration_ms,retry_count,status,error_msg)
               VALUES (?,?,?,?,?,?,?,?)""",
            (call["call_id"], call["tool_name"], call.get("params", "{}"),
             call.get("result", "")[:1000], call.get("duration_ms", 0),
             call.get("retry_count", 0), call.get("status", "success"),
             call.get("error_msg", "")),
        ).lastrowid

    def get_tool_calls(self, limit: int = 50, tool_name: str = None) -> list[dict]:
        if tool_name:
            return self._exec(
                "SELECT * FROM tool_calls WHERE tool_name=? ORDER BY created_at DESC LIMIT ?",
                (tool_name, limit), fetch=True,
            )
        return self._exec(
            "SELECT * FROM tool_calls ORDER BY created_at DESC LIMIT ?", (limit,), fetch=True,
        )

    def tool_call_count(self) -> int:
        rows = self._exec("SELECT COUNT(*) as c FROM tool_calls", fetch=True)
        return rows[0]["c"] if rows else 0

    def tool_call_stats(self) -> dict:
        """按工具聚合统计"""
        rows = self._exec(
            "SELECT tool_name, COUNT(*) as cnt, AVG(duration_ms) as avg_ms, "
            "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success_cnt, "
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as fail_cnt "
            "FROM tool_calls GROUP BY tool_name ORDER BY cnt DESC",
            fetch=True,
        )
        return [dict(r) for r in rows]

    # ==================== sample_stats (v3.1) ====================

    def save_sample_stats(self, stats: dict) -> int:
        return self._exec(
            """INSERT INTO sample_stats (total_count,bin_0_20,bin_20_40,bin_40_60,bin_60_80,bin_80_100,source_breakdown)
               VALUES (?,?,?,?,?,?,?)""",
            (stats["total"], stats.get("bins", {}).get("0-20", 0),
             stats.get("bins", {}).get("20-40", 0), stats.get("bins", {}).get("40-60", 0),
             stats.get("bins", {}).get("60-80", 0), stats.get("bins", {}).get("80-100", 0),
             json.dumps(stats.get("sources", {}), ensure_ascii=False)),
        ).lastrowid

    def get_latest_sample_stats(self) -> dict | None:
        rows = self._exec("SELECT * FROM sample_stats ORDER BY snapshot_at DESC LIMIT 1", fetch=True)
        if not rows:
            return None
        r = dict(rows[0])
        try: r["source_breakdown"] = json.loads(r["source_breakdown"])
        except Exception: pass
        return r

    def get_sample_history(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self._exec(
            "SELECT total_count,bin_0_20,bin_20_40,bin_40_60,bin_60_80,bin_80_100,snapshot_at FROM sample_stats ORDER BY snapshot_at DESC LIMIT ?",
            (limit,), fetch=True,
        )]


# 全局单例
_db_instance = None


def get_db() -> JobDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = JobDB()
    return _db_instance
