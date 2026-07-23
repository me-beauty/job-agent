#!/usr/bin/env python3
"""异步任务管理器 — 通用任务生命周期管理（DB 持久化）"""

import datetime
import threading
from typing import Optional

from db import get_db
from utils.logger import get_logger

logger = get_logger("engine.task")

_lock = threading.Lock()
_memory_tasks: dict = {}  # 实时内存缓存


class TaskManager:
    """
    通用异步任务管理。

    用法:
        tm = TaskManager()
        tid = tm.create("search", {"keyword": "..."})
        # ... 后台执行 ...
        tm.update(tid, "done", {"count": 5})
        status = tm.get(tid)  # {"status": "done", "result": {"count": 5}, ...}
    """

    @staticmethod
    def create(task_type: str, params: dict = None, status: str = "pending") -> str:
        """创建任务，返回 task_id"""
        task_id = f"{task_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

        with _lock:
            _memory_tasks[task_id] = {"type": task_type, "status": status, "result": None}

        try:
            db = get_db()
            db.add_task(task_id, task_type, status, params or {})
        except Exception as e:
            logger.warning(f"DB task create failed (will use memory): {e}")

        return task_id

    @staticmethod
    def update(task_id: str, status: str, result: dict = None, error_msg: str = ""):
        """更新任务状态"""
        with _lock:
            if task_id in _memory_tasks:
                _memory_tasks[task_id]["status"] = status
                _memory_tasks[task_id]["result"] = result

        try:
            db = get_db()
            db.update_task(task_id, status, result or {}, error_msg)
        except Exception as e:
            logger.warning(f"DB task update failed (will use memory): {e}")

    @staticmethod
    def get(task_id: str) -> Optional[dict]:
        """查询任务状态（优先 DB，回退内存）"""
        # 先查内存
        with _lock:
            mem = _memory_tasks.get(task_id)

        # 再查 DB
        try:
            db = get_db()
            db_task = db.get_task(task_id)
            if db_task:
                return db_task
        except Exception:
            pass

        if mem:
            return {"task_id": task_id, **mem}
        return None

    @staticmethod
    def list(limit: int = 50) -> list:
        """列出最近任务"""
        try:
            return get_db().list_tasks(limit=limit)
        except Exception:
            with _lock:
                return [{"task_id": k, **v} for k, v in list(_memory_tasks.items())[-limit:]]

    @staticmethod
    def run_in_thread(task_id: str, fn, *args, **kwargs):
        """后台线程执行 fn，自动更新任务状态"""

        def _wrapper():
            try:
                result = fn(*args, **kwargs)
                TaskManager.update(task_id, "done", result)
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
                TaskManager.update(task_id, "error", error_msg=str(e))

        t = threading.Thread(target=_wrapper, daemon=True)
        t.start()
        return t
