#!/usr/bin/env python3
"""
日报后处理工具 — 去重、历史对比、jobhunt-cli 集成。
快速模式 & 精准模式共享。
"""

import datetime
import json
import subprocess
from pathlib import Path

# ============================================================
# jobhunt-cli：大厂官方招聘网站直搜
# ============================================================

JOBHUNT_COMPANIES = [
    "bytedance", "meituan", "baidu", "jd",
    "tencent", "kuaishou", "xiaomi", "huawei",
]

JOBHUNT_KEYWORDS = ["数据科学", "数据分析", "大数据"]
JOBHUNT_LOCATIONS = ["北京", "天津", "石家庄", "雄安"]
JOBHUNT_LIMIT = 10
JOBHUNT_PROMPT_LIMIT = 20  # 注入报告的最大条数

COMPANY_NAMES = {
    "bytedance": "字节跳动", "meituan": "美团", "baidu": "百度",
    "jd": "京东", "tencent": "腾讯", "kuaishou": "快手",
    "xiaomi": "小米", "huawei": "华为",
}


def check_jobhunt_available():
    """检测 job 命令是否可用。"""
    try:
        r = subprocess.run(
            ["job", "--version"], capture_output=True,
            encoding='utf-8', errors='ignore', shell=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def fetch_jobhunt_jobs(keyword, location, companies=None, limit=None):
    """搜索一家或多家公司官网。返回 list[dict]."""
    if companies is None:
        companies = JOBHUNT_COMPANIES
    if limit is None:
        limit = JOBHUNT_LIMIT

    results = []
    for company in companies:
        try:
            cmd = ["job", company, "search", keyword,
                   "--limit", str(limit), "--format", "json"]
            if location:
                cmd.extend(["--location", location])
            r = subprocess.run(cmd, capture_output=True, encoding='utf-8',
                               errors='ignore', shell=True, timeout=30)
            if r.returncode != 0:
                continue
            data = json.loads(r.stdout)
            if not isinstance(data, list):
                continue
            for job in data:
                results.append({
                    "company": COMPANY_NAMES.get(company, company),
                    "position": job.get("name", ""),
                    "location": job.get("location_names", location),
                    "url": job.get("url", ""),
                    "source": "官方招聘",
                })
        except (json.JSONDecodeError, subprocess.TimeoutExpired, Exception):
            continue
    return results


def collect_jobhunt_data():
    """批量采集 jobhunt-cli 数据。返回 (rows, stats)。"""
    all_rows = []
    for kw in JOBHUNT_KEYWORDS:
        for loc in JOBHUNT_LOCATIONS:
            all_rows.extend(fetch_jobhunt_jobs(kw, loc))

    seen = set()
    deduped = []
    for r in all_rows:
        key = f"{r['company']}|{r['position']}"
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return deduped, {
        "raw_count": len(all_rows),
        "after_dedup": len(deduped),
        "companies_searched": len(JOBHUNT_COMPANIES),
    }


def _title_relevance(title):
    """岗位标题与数据的相关度打分。"""
    score, t = 0, title.lower()
    if "数据" in t: score += 10
    if "数据分析" in t or "数据科学" in t or "大数据" in t: score += 5
    if "实习" in t: score += 3
    if "算法" in t or "ai" in t or "机器学习" in t: score += 2
    if "总监" in t or "经理" in t or "负责人" in t: score -= 5
    if "销售" in t or "客户经理" in t: score -= 10
    return score


def filter_and_rank_jobhunt(rows, top_n=None):
    """按相关度过滤排序，返回 TopN + 过滤后的总数。"""
    if top_n is None:
        top_n = JOBHUNT_PROMPT_LIMIT
    scored = [r for r in rows if _title_relevance(r["position"]) > 0]
    scored.sort(key=lambda x: _title_relevance(x["position"]), reverse=True)
    return scored[:top_n], len(scored)


def inject_jobhunt_rows(content, jobhunt_rows):
    """
    在 Claude 生成的报告中注入 jobhunt 官方招聘数据。
    优先合并到 WebSearch 表格中，如果表格格式不标准则追加独立区块。
    返回 (注入后的内容, 注入统计或None)
    """
    if not jobhunt_rows:
        return content, None

    # 先尝试表格合并模式
    merged, stats = _merge_table(content, jobhunt_rows)
    if merged is not None:
        return merged, stats

    # 回退：追加独立「官方招聘」表格
    return _append_standalone_table(content, jobhunt_rows)


def _merge_table(content, jobhunt_rows):
    """尝试合并到 Claude 的标准表格中。成功返回 (content, stats)，失败返回 (None, None)。"""
    lines = content.split("\n")

    header_idx = data_start = data_end = None
    for i, line in enumerate(lines):
        if "搜索结果汇总表" in line or "岗位汇总表" in line:
            for j in range(i + 1, min(i + 15, len(lines))):
                if lines[j].strip().startswith("|") and ("公司" in lines[j] or "岗位" in lines[j]):
                    header_idx = j
                    break
            break
    if header_idx is None:
        return None, None

    if "数据来源" in lines[header_idx]:
        return None, None  # 已经注入过

    for j in range(header_idx + 1, min(header_idx + 3, len(lines))):
        if lines[j].strip().startswith("|---"):
            data_start = j + 1
            break
    if data_start is None:
        return None, None

    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if (line.startswith("---") or line.startswith("## ")) and i > data_start:
            data_end = i
            break
        if not line.startswith("|") and line.strip() != "":
            data_end = i
            break
    if data_end is None:
        data_end = len(lines)

    # 加「数据来源」列（插在「地点」之后，「双休」之前 = 索引 4）
    SRC_COL = 4
    header_cells = [c.strip() for c in lines[header_idx].strip("|").split("|")]
    if len(header_cells) <= SRC_COL:
        SRC_COL = len(header_cells)  # 表格列不够时追加到末尾
    header_cells.insert(SRC_COL, "数据来源")
    lines[header_idx] = "| " + " | ".join(header_cells) + " |"

    sep_idx = header_idx + 1
    if sep_idx < len(lines) and "---" in lines[sep_idx]:
        sep_cells = [c.strip() for c in lines[sep_idx].strip("|").split("|")]
        sep_cells.insert(SRC_COL, ":---:")
        lines[sep_idx] = "|" + "|".join(sep_cells) + "|"

    row_num = 0
    existing_keys = set()
    for i in range(data_start, data_end):
        line = lines[i].strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        row_num += 1
        cells.insert(SRC_COL, "网络搜索")
        cells[0] = str(row_num)
        lines[i] = "| " + " | ".join(cells) + " |"
        existing_keys.add(f"{_normalize(cells[1])}|{_normalize(cells[2])}")

    new_count = 0
    for jr in jobhunt_rows:
        key = f"{_normalize(jr['company'])}|{_normalize(jr['position'])}"
        if key in existing_keys:
            continue
        existing_keys.add(key)
        row_num += 1
        row = (
            f"| {row_num} | {jr['company']} | {jr['position']} | {jr['location']} |"
            f" 官方招聘 | ❌ | ❌ | ❌ | ⭐ | JH |"
        )
        lines.insert(data_end, row)
        data_end += 1
        new_count += 1

    if new_count == 0:
        return None, None

    return "\n".join(lines), {"injected": new_count}


def _append_standalone_table(content, jobhunt_rows):
    """在报告末尾追加独立的官方招聘区块。"""
    lines = content.split("\n")

    section = [
        "",
        "---",
        "",
        "## 📊 官方招聘直搜（jobhunt-cli）",
        "",
        "> 以下数据从各公司**官方招聘网站**直接采集，独立于 WebSearch 结果。",
        "> 因 WebSearch 表格格式不标准，以独立表格呈现。",
        "",
        "| # | 公司 | 岗位 | 地点 | 双休 | 住宿 | 薪资 | 匹配 |",
        "|---|------|------|------|:---:|:---:|:---:|:---:|",
    ]

    for i, jr in enumerate(jobhunt_rows, 1):
        section.append(
            f"| {i} | {jr['company']} | {jr['position']} | {jr['location']} "
            f"| ❌ | ❌ | ❌ | ⭐ |"
        )

    return "\n".join(lines) + "\n".join(section) + "\n", {"injected": len(jobhunt_rows)}


def parse_table_rows(content):
    """
    从报告的搜索结果汇总表中提取岗位条目。
    返回 list[dict]，每个 dict: company, position, location
    """
    lines = content.split("\n")

    # 定位表格头
    header_idx = None
    for i, line in enumerate(lines):
        if "搜索结果汇总表" in line:
            for j in range(i + 1, min(i + 10, len(lines))):
                if lines[j].strip().startswith("|") and "公司" in lines[j]:
                    header_idx = j
                    break
            break
    if header_idx is None:
        return []

    # 跳过分隔行，找到数据起始行
    data_start = None
    for j in range(header_idx + 1, min(header_idx + 3, len(lines))):
        if lines[j].strip().startswith("|---"):
            data_start = j + 1
            break
    if data_start is None:
        return []

    # 收集数据行
    rows = []
    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line.startswith("|"):
            break  # 表格结束
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        # 表格列：| # | 公司/来源 | 岗位名称 | 地点 | ...
        rows.append({
            "company": cells[1] if len(cells) > 1 else cells[0],
            "position": cells[2] if len(cells) > 2 else cells[1],
            "location": cells[3] if len(cells) > 3 else "",
        })
    return rows


def _normalize(text):
    """标准化文本用于比较：去空格、全角半角统一、小写"""
    text = text.strip()
    text = text.replace("　", "").replace(" ", "")
    text = text.replace("（", "(").replace("）", ")")
    text = text.lower()
    return text


def deduplicate_table(content, print_callback=None):
    """
    对日报中的搜索结果汇总表按「公司+岗位」去重。
    返回 (去重后的内容, 统计信息或None)
    """
    lines = content.split("\n")

    # 定位表格区块
    table_start = None
    table_end = None
    for i, line in enumerate(lines):
        if table_start is None and "搜索结果汇总表" in line:
            for j in range(i + 1, min(i + 10, len(lines))):
                if lines[j].strip().startswith("|") and "公司" in lines[j]:
                    table_start = j
                    break
            if table_start:
                for j in range(table_start + 1, min(table_start + 3, len(lines))):
                    if lines[j].strip().startswith("|---"):
                        table_start = j + 1
                        break
        if table_start is not None and table_end is None:
            if i > (table_start or 0) and (lines[i].strip().startswith("---") or lines[i].strip().startswith("## ")):
                table_end = i
                break
            if i > (table_start or 0) and not lines[i].strip().startswith("|"):
                if lines[i].strip() == "" and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                    continue
                table_end = i
                break

    if table_start is None or table_end is None or table_end <= table_start:
        return content, None

    data_rows = []
    for i in range(table_start, table_end):
        line = lines[i].strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue
        data_rows.append((i, cells))

    if len(data_rows) <= 1:
        return content, None

    seen = set()
    duplicate_indices = set()
    for row_idx, cells in data_rows:
        company = _normalize(cells[1] if len(cells) > 1 else "0")
        position = _normalize(cells[2] if len(cells) > 2 else "0")
        key = f"{company}|{position}"
        if key in seen:
            duplicate_indices.add(row_idx)
        else:
            seen.add(key)

    if not duplicate_indices:
        return content, None

    removed_count = len(duplicate_indices)
    new_lines = [line for i, line in enumerate(lines) if i not in duplicate_indices]
    stats_line = f"\n> 📊 **去重统计**：去重前 {len(data_rows)} 条，去重后 {len(data_rows) - removed_count} 条（去除 {removed_count} 条重复）\n"

    insert_pos = len(new_lines)
    for i, line in enumerate(new_lines):
        if i > table_start and (line.strip().startswith("---") or line.strip().startswith("## ")):
            insert_pos = i
            break

    new_lines.insert(insert_pos, stats_line)
    stats = {"before": len(data_rows), "after": len(data_rows) - removed_count, "removed": removed_count}

    if print_callback:
        print_callback(stats)

    return "\n".join(new_lines), stats


def find_yesterday_report(report_dir):
    """找到昨天的日报文件。返回 Path 或 None。"""
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    y_str = yesterday.strftime("%Y-%m-%d")
    candidates = [
        report_dir / f"daily_report_{y_str}_自动版.md",
        report_dir / f"daily_report_{y_str}.md",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def compare_with_yesterday(today_content, yesterday_path=None, report_dir=None):
    """
    对比今天和昨天的岗位列表。
    返回 (change_section: str, stats: dict)。
    """
    if yesterday_path is None and report_dir is not None:
        yesterday_path = find_yesterday_report(report_dir)
    if yesterday_path is None:
        return "", {"new_count": 0, "removed_count": 0, "unchanged_count": 0}

    yesterday_text = yesterday_path.read_text(encoding="utf-8")
    yesterday_rows = parse_table_rows(yesterday_text)
    today_rows = parse_table_rows(today_content)

    if not yesterday_rows:
        return "", {"new_count": 0, "removed_count": 0, "unchanged_count": 0}

    def make_key(r):
        return f"{_normalize(r['company'])}|{_normalize(r['position'])}"

    def make_label(r):
        return f"{r['company']} — {r['position']}"

    yesterday_map = {make_key(r): make_label(r) for r in yesterday_rows}
    today_map = {make_key(r): make_label(r) for r in today_rows}

    new_keys = set(today_map.keys()) - set(yesterday_map.keys())
    removed_keys = set(yesterday_map.keys()) - set(today_map.keys())
    unchanged = set(today_map.keys()) & set(yesterday_map.keys())

    if not new_keys and not removed_keys:
        section = (
            "## 📈 与昨日对比\n\n"
            f"> 与昨日完全一致，无新增也无下架岗位（{len(unchanged)} 个岗位不变）。\n\n"
        )
        return section, {
            "new_count": 0, "removed_count": 0, "unchanged_count": len(unchanged),
            "yesterday_date": yesterday_path.stem,
        }

    lines = ["## 📈 与昨日对比\n"]
    lines.append("| 变化 | 数量 |")
    lines.append("|------|:---:|")
    lines.append(f"| 🆕 新增 | **{len(new_keys)}** |")
    lines.append(f"| ❌ 已下架 | **{len(removed_keys)}** |")
    lines.append(f"| ➖ 不变 | {len(unchanged)} |")
    lines.append("")

    if new_keys:
        lines.append("### 🆕 今日新增")
        for i, key in enumerate(sorted(new_keys), 1):
            lines.append(f"{i}. {today_map[key]}")
        lines.append("")

    if removed_keys:
        lines.append("### ❌ 昨日有、今日无（已下架）")
        for i, key in enumerate(sorted(removed_keys), 1):
            lines.append(f"{i}. {yesterday_map[key]}")
        lines.append("")

    return "\n".join(lines) + "\n---\n\n", {
        "new_count": len(new_keys),
        "removed_count": len(removed_keys),
        "unchanged_count": len(unchanged),
        "yesterday_date": yesterday_path.stem,
    }
