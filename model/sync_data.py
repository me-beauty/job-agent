#!/usr/bin/env python3
"""
数据采集自动化同步脚本 — 从多源采集岗位并同步到 DB + 向量库。

用法:
  python -m model.sync_data                    # 全量同步
  python -m model.sync_data --source browser   # 仅 browser CSV
  python -m model.sync_data --export-csv       # 导出 DB 到 CSV

集成到 API:
  POST /api/data/sync   → 触发同步
  GET  /api/data/stats  → 样本监控面板
"""

import argparse
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def sync_from_csv() -> int:
    """从项目目录 *.csv 同步到 DB"""
    from db import get_db
    import csv
    db = get_db()
    count = 0
    for f in sorted(ROOT.glob("*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                db.add_job({
                    "source": f"csv:{f.name}",
                    "title": row.get("title") or row.get("position", ""),
                    "company": row.get("company", ""),
                    "description": row.get("description", ""),
                    "location": row.get("location", ""),
                    "salary": row.get("salary", ""),
                })
                count += 1
        print(f"  CSV: {f.name} -> {count} rows")
    return count


def sync_from_markdown() -> int:
    """从日报 .md 同步到 DB"""
    from db import get_db
    from report_utils import parse_table_rows
    db = get_db()
    count = 0
    for f in sorted(ROOT.glob("daily_report_*.md"))[:5]:
        rows = parse_table_rows(f.read_text(encoding="utf-8"))
        for r in rows:
            db.add_job({
                "source": f"md:{f.name}",
                "title": r.get("position", ""),
                "company": r.get("company", ""),
                "location": r.get("location", ""),
            })
            count += 1
        print(f"  MD: {f.name} -> {count} rows")
    return count


def sync_from_db_to_vector() -> int:
    """DB 岗位 → 向量库"""
    from db import get_db
    from model.vector_store import get_vector_store
    db = get_db()
    vs = get_vector_store()
    jobs = db.get_jobs(limit=5000)
    if not jobs:
        print("  No jobs in DB")
        return 0
    items = [{**j, "id": str(j.get("id", "")),
              "text": f"{j.get('title','')} {j.get('company','')} {j.get('description','')}"}
             for j in jobs]
    cnt = vs.add_jobs(items)
    print(f"  DB->Vector: {cnt} jobs indexed")
    return cnt


def export_csv(output: str = None) -> str:
    """导出 DB 岗位到 CSV"""
    from db import get_db
    import csv
    db = get_db()
    jobs = db.get_jobs(limit=5000)
    if output is None:
        output = str(ROOT / f"jobs_export_{datetime.date.today().strftime('%Y%m%d')}.csv")
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["source","title","company","description","location","salary","match_score","created_at"])
        writer.writeheader()
        for j in jobs:
            writer.writerow({k: j.get(k, "") for k in writer.fieldnames})
    print(f"  Exported: {output} ({len(jobs)} jobs)")
    return output


def full_sync() -> dict:
    """全量同步：多源 → DB → 向量库 → 快照"""
    results = {}
    results["csv"] = sync_from_csv()
    results["md"] = sync_from_markdown()
    results["vector"] = sync_from_db_to_vector()

    from model.monitor import SampleMonitor
    sm = SampleMonitor()
    results["snapshot"] = sm.take_snapshot()

    total = results["csv"] + results["md"]
    print(f"\nSync complete: {total} jobs from files, {results['vector']} vectorized")
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Job Agent data sync")
    p.add_argument("--source", choices=["csv","md","vector","all"], default="all")
    p.add_argument("--export-csv", action="store_true")
    p.add_argument("--output")
    args = p.parse_args()

    if args.export_csv:
        export_csv(args.output)
    elif args.source == "csv":
        sync_from_csv()
    elif args.source == "md":
        sync_from_markdown()
    elif args.source == "vector":
        sync_from_db_to_vector()
    else:
        full_sync()
