#!/usr/bin/env python3
"""
MCP 短期记忆缓存 + 工具调用链路日志 (v3.1 升级版)。

升级内容:
  - 工具调用日志 → 双写 (JSONL 文件 + SQLite DB)
  - 新增任务参数前置校验
  - 简易任务规划编排
"""

import hashlib
import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("mcp.memory")


class MCPMemory:
    """记忆缓存 + 调用日志持久化"""

    def __init__(self, max_size: int = 128, ttl: int = None):
        self.max_size = max_size
        self.ttl = ttl or settings.MCP_MEMORY_TTL
        self._cache: dict[str, tuple] = {}
        self._lock = Lock()
        self._call_log_path = settings.MCP_CALL_LOG
        self._call_log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"MCPMemory v3.1: max={max_size} ttl={self.ttl}s log={self._call_log_path}")

    def _make_key(self, tool_name: str, params: str) -> str:
        return hashlib.md5(f"{tool_name}::{params}".encode()).hexdigest()

    def get(self, tool_name: str, params: dict) -> dict | None:
        key = self._make_key(tool_name, json.dumps(params, sort_keys=True, ensure_ascii=False))
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() < entry[1]:
                return entry[0]
            if entry:
                del self._cache[key]
        return None

    def put(self, tool_name: str, params: dict, result: dict):
        key = self._make_key(tool_name, json.dumps(params, sort_keys=True, ensure_ascii=False))
        with self._lock:
            if len(self._cache) >= self.max_size:
                oldest = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest]
            self._cache[key] = (result, time.time() + self.ttl)

    def log_call(self, tool_name: str, params: dict, result: Any,
                 duration_ms: float, retry_count: int = 0, error: str = "",
                 call_id: str = ""):
        """双写: JSONL 文件 + SQLite DB"""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tool": tool_name,
            "params": json.dumps(params, ensure_ascii=False),
            "result_summary": str(result)[:200] if result else "",
            "duration_ms": round(duration_ms, 1),
            "retry_count": retry_count,
            "error": error,
        }
        # File
        try:
            with open(self._call_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"File log failed: {e}")

        # DB
        try:
            from db import get_db
            cid = call_id or self._make_key(tool_name, json.dumps(params or {}, sort_keys=True))
            get_db().log_tool_call({
                "call_id": cid,
                "tool_name": tool_name,
                "params": json.dumps(params or {}, ensure_ascii=False),
                "result": str(result)[:1000] if result else "",
                "duration_ms": round(duration_ms, 1),
                "retry_count": retry_count,
                "status": "failed" if error else "success",
                "error_msg": error[:200],
            })
        except Exception as e:
            logger.debug(f"DB log skipped: {e}")

    def stats(self) -> dict:
        with self._lock:
            active = sum(1 for v in self._cache.values() if v[1] > time.time())
            return {"total_cached": len(self._cache), "active": active, "max_size": self.max_size}

    def get_call_stats(self) -> dict:
        """从 DB 读取调用统计"""
        try:
            from db import get_db
            db = get_db()
            total = db.tool_call_count()
            stats = db.tool_call_stats()
            return {"total_calls": total, "by_tool": stats}
        except Exception as e:
            return {"error": str(e)}


# ============================================================
# 参数前置校验 (v3.1)
# ============================================================

TOOL_SCHEMAS: dict[str, dict] = {
    "search_jobs": {
        "required": ["keyword"],
        "type_check": {"keyword": str, "sites": list, "city": str, "max_per_site": int},
    },
    "apply_job": {
        "required": ["url"],
        "type_check": {"url": str, "resume_path": str},
    },
    "train_job_match_model": {
        "type_check": {"epochs": (int, float), "lr": (int, float)},
    },
    "get_job_match_score": {
        "required": ["resume_text", "job_texts"],
        "type_check": {"resume_text": str, "job_texts": list},
    },
    "scrape_to_csv": {
        "required": ["url"],
        "type_check": {"url": str},
    },
    "take_screenshot": {
        "required": ["url"],
        "type_check": {"url": str},
    },
    "browser_status": {},
}


def validate_params(tool_name: str, params: dict) -> tuple[bool, str]:
    """
    前置校验工具参数。

    Returns:
        (valid: bool, error_msg: str)
    """
    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        return True, ""  # 未知工具不校验

    # 必填检查
    for field in schema.get("required", []):
        if field not in params or params[field] in (None, "", [], {}):
            return False, f"参数 '{field}' 是必填项"

    # 类型检查
    for field, expected in schema.get("type_check", {}).items():
        if field in params and params[field] is not None:
            types = expected if isinstance(expected, tuple) else (expected,)
            if not isinstance(params[field], types):
                return False, f"参数 '{field}' 类型错误: 期望 {types}, 实际 {type(params[field]).__name__}"

    return True, ""


# ============================================================
# 简易任务规划编排 (v3.1)
# ============================================================

class TaskPlanner:
    """
    简易任务规划 — 将复杂指令分解为有序 MCP 工具调用序列。

    用法:
        planner = TaskPlanner()
        steps = planner.plan("搜索石家庄数据分析实习，给岗位打分，投递70分以上的")
        for step in steps:
            result = await call_tool(step["tool"], step["params"])
    """

    PATTERNS: dict[str, list[dict]] = {
        "搜索并打分": [
            {"tool": "search_jobs", "desc": "搜索岗位"},
            {"tool": "get_job_match_score", "desc": "匹配打分"},
        ],
        "搜索打分投递": [
            {"tool": "search_jobs", "desc": "搜索岗位"},
            {"tool": "get_job_match_score", "desc": "匹配打分"},
            {"tool": "apply_job", "desc": "投递高分岗位"},
        ],
        "训练并打分": [
            {"tool": "train_job_match_model", "desc": "训练模型"},
            {"tool": "get_job_match_score", "desc": "匹配打分"},
        ],
    }

    def plan(self, instruction: str) -> list[dict]:
        """根据用户指令匹配规划模板"""
        instruction_lower = instruction.lower()
        for pattern_name, steps in self.PATTERNS.items():
            # 简单关键词匹配
            keywords = pattern_name.replace("并", " ").split()
            if all(kw in instruction_lower for kw in keywords):
                logger.info(f"Planning: '{pattern_name}' for '{instruction[:50]}...'")
                return steps
        # 默认: 单步 search
        logger.info(f"No plan matched, default to single: {instruction[:50]}")
        return [{"tool": "search_jobs", "desc": "搜索岗位"}]

    def add_pattern(self, name: str, steps: list[dict]):
        self.PATTERNS[name] = steps
