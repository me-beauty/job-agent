#!/usr/bin/env python3
"""
分级日志系统 — 文件 + 控制台双输出。

用法:
  from utils.logger import get_logger
  logger = get_logger(__name__)
  logger.info("Task started")
  logger.warning("Rate limit approaching")
  logger.error("Browser crashed", exc_info=True)

级别: 环境变量 LOG_LEVEL 控制 (DEBUG/INFO/WARNING/ERROR)，默认 INFO
日志文件: logs/job_agent_YYYYMMDD.log (按天轮转)
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_loggers: dict[str, logging.Logger] = {}


def _make_handler(level: int, fmt: str, stream=None, filename: str = None):
    h = logging.StreamHandler(stream) if stream else logging.FileHandler(filename, encoding="utf-8")
    h.setLevel(level)
    h.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    return h


def setup_logger(name: str = "job_agent", level: str = None) -> logging.Logger:
    """创建并配置 logger"""
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    lvl = getattr(logging, level.upper(), logging.INFO)

    today = datetime.now().strftime("%Y%m%d")
    log_file = str(LOG_DIR / f"job_agent_{today}.log")

    logger = logging.getLogger(name)
    logger.setLevel(lvl)
    logger.propagate = False

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    fmt = "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s"

    logger.addHandler(_make_handler(lvl, fmt, stream=sys.stdout))
    logger.addHandler(_make_handler(lvl, fmt, filename=log_file))

    return logger


def get_logger(name: str = "job_agent") -> logging.Logger:
    """获取或创建 logger（缓存复用）"""
    if name not in _loggers:
        _loggers[name] = setup_logger(name)
    return _loggers[name]


# 根 logger
root_logger = setup_logger("job_agent")
