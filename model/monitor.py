#!/usr/bin/env python3
"""
样本监控工具 — 持续追踪训练样本数量与分布。

独立模块，供 model 和 web panel 调用。

用法:
    from model.monitor import SampleMonitor
    sm = SampleMonitor()
    sm.take_snapshot()          # 记录当前快照到 DB
    report = sm.report()        # 获取最近统计
"""

import datetime
from collections import Counter
from pathlib import Path

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("model.monitor")


class SampleMonitor:
    """训练样本数量 & 分布持续监控"""

    def __init__(self):
        pass

    def count_all_sources(self) -> dict:
        """统计各数据源的岗位数量"""
        from db import get_db
        db = get_db()
        sources = {}
        for s in ["csv", "md", "jobhunt", "websearch", "browser", "semantic", "unknown"]:
            c = db.job_count(source=s)
            if c > 0:
                sources[s] = c
        return sources

    def distribution_bins(self) -> dict:
        """按 match_score 分桶统计"""
        from db import get_db
        db = get_db()
        jobs = db.get_jobs(limit=5000)
        bins = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
        for j in jobs:
            s = j.get("match_score", 0) or 0
            if s < 20: bins["0-20"] += 1
            elif s < 40: bins["20-40"] += 1
            elif s < 60: bins["40-60"] += 1
            elif s < 80: bins["60-80"] += 1
            else: bins["80-100"] += 1
        return bins

    def take_snapshot(self) -> dict:
        """采集当前快照写入 DB"""
        from db import get_db
        db = get_db()
        total = db.job_count()
        bins = self.distribution_bins()
        sources = self.count_all_sources()
        stats = {"total": total, "bins": bins, "sources": sources}
        db.save_sample_stats(stats)
        logger.info(f"Sample snapshot: total={total} bins={bins}")
        return stats

    def report(self) -> dict:
        """最近一次快照"""
        from db import get_db
        db = get_db()
        latest = db.get_latest_sample_stats()
        if latest:
            return latest
        # 如果没快照，现场采集
        return self.take_snapshot()

    def history(self, limit: int = 20) -> list[dict]:
        """历史快照趋势"""
        from db import get_db
        return get_db().get_sample_history(limit=limit)

    def balance_summary(self) -> dict:
        """不均衡摘要"""
        r = self.report()
        bins = {}
        for k in ["0-20", "20-40", "40-60", "60-80", "80-100"]:
            bins[k] = r.get(f"bin_{k}") or r.get("bins", {}).get(k, 0)
        max_bin = max(bins.values()) if bins.values() else 1
        min_bin = min(v for v in bins.values() if v > 0) if any(v > 0 for v in bins.values()) else 1
        ratio = round(max_bin / min_bin, 1) if min_bin > 0 else 999
        return {
            "total": r.get("total_count", 0),
            "balanced": ratio < 2.0,
            "imbalance_ratio": ratio,
            "bins": bins,
        }
