#!/usr/bin/env python3
"""
自动日报生成器 — 快速模式
每天定时运行，只看搜索结果摘要，不做链接点开核实。
独立于高精度手动模式（"执行日报任务"触发）。

双数据源：
  数据源 A: WebSearch（7 组关键词 × 前 3 条 = 最多 21 条）
  数据源 B: jobhunt-cli（大厂官方招聘网站直搜）

7 组关键词：石家庄 / 雄安 / 北京 / 天津 / 河北 / 保定 / 唐山
每组取前 3 条 → 最多 21 条 → 按摘要匹配 双休/住宿/薪资
输出：daily_report_YYYY-MM-DD_自动版.md
"""

import subprocess
import datetime
import os
import sys
import io
from pathlib import Path

# 强制 stdout 使用 UTF-8，解决中文 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

# 项目目录（桌面 job_agent 文件夹）
DESKTOP = Path.home() / "Desktop" / "job_agent"

# 共享工具（去重 + 历史对比 + jobhunt）
from report_utils import (
    deduplicate_table, compare_with_yesterday, find_yesterday_report,
    check_jobhunt_available, collect_jobhunt_data,
    filter_and_rank_jobhunt, inject_jobhunt_rows,
    JOBHUNT_COMPANIES, JOBHUNT_KEYWORDS, JOBHUNT_LOCATIONS,
)


# ============================================================
# 快速模式搜索指令（7 个城市关键词 × 每组前 3 条）
# ============================================================
QUICK_SEARCH_PROMPT = """你是求职搜索助手。请使用 WebSearch 工具对以下 **7 个关键词** 分别执行一次搜索，**只看搜索结果摘要，不要点开链接，不要用 WebFetch**。每个关键词取排名前 3 条结果。

---

## 🔑 7 组关键词

| 编号 | 关键词 | 说明 |
|------|--------|------|
| K1 | `石家庄 数据科学 OR 数据分析 实习 2027届 OR 2026届 本科` | 河北省会 |
| K2 | `雄安 数据 OR 数字化 实习 2027 OR 2026 本科 提供住宿` | 雄安新区 |
| K3 | `北京 数据科学 OR 数据分析 实习 2027届 本科 房补 OR 住宿` | 首都周边 |
| K4 | `天津 数据 实习 2027届 OR 2026届 本科 数据分析 OR 大数据` | 天津周边 |
| K5 | `河北 数据科学 OR 大数据 实习 2027 OR 2026 本科` | 河北全境 |
| K6 | `保定 数据 OR 信息技术 实习 2027 OR 2026 本科` | 保定市 |
| K7 | `唐山 大数据 OR 数据分析 实习 2027 OR 2026 本科` | 唐山市 |

---

## 🔍 筛选规则

从每条搜索结果的**摘要文字**中，检测以下关键词：

| 条件类别 | 摘要中出现的关键词 | 标记 |
|----------|-------------------|:---:|
| **📌 双休** | "双休" / "周末双休" / "做五休二" / "标准工时" | ✅ 或 ❌ |
| **🏠 住宿** | "住宿" / "房补" / "包住" / "宿舍" / "提供公寓" / "住宿补贴" / "免费公寓" | ✅ 或 ❌ |
| **💰 薪资** | "工资" / "薪资" / "补贴" / "津贴" / "元/天" / "元/月" / "实习工资" / "日薪" / "月薪" | ✅ 或 ❌ |

> 摘要中**未明确提到**的条件一律标记为 ❌（从严判断）。

---

## 📊 输出格式

输出一个完整的 Markdown 文件，结构如下：

```markdown
# 📅 自动日报 — {today}

> ⚡ **快速模式** | 仅基于搜索摘要 | 未核实链接详情
> 🕐 生成时间：{date}
> 🔍 搜索范围：7 组关键词 × 每组前 3 条 = 最多 21 条结果

---

## 📊 搜索结果汇总表

| # | 公司/来源 | 岗位名称 | 地点 | 双休 | 住宿 | 薪资 | 匹配 | 关键词 |
|---|----------|----------|------|:---:|:---:|:---:|:---:|--------|
| 1 | 字节跳动 | 数据科学实习生 | 北京 | ❌ | ✅ | ✅ | ⭐⭐ | K3 |
| 2 | ... | ... | ... | ... | ... | ... | ... | ... |

（列出所有有至少 1 项匹配的岗位，0 匹配的跳过）

> ⚠️ **去重规则**：如果两个岗位的「公司/来源」和「岗位名称」完全相同（或高度相似），只保留第一条（取最先出现的搜索结果）。在表格后面注明「去重前 X 条，去重后 Y 条」。

---

## 🏆 按匹配度分组

### ⭐⭐⭐ 高匹配（同时满足双休 + 住宿 + 薪资，3/3）
> 列出所有 ⭐⭐⭐ 岗位，如果没有则写"本次搜索未发现 ⭐⭐⭐ 岗位"

### ⭐⭐ 中匹配（满足任意 2 项）
> 列出所有 ⭐⭐ 岗位

### ⭐ 低匹配（满足任意 1 项）
> 列出所有 ⭐ 岗位

---

## 📈 各关键词搜索概况

| 关键词编号 | 关键词简述 | 搜索结果数 | 有匹配结果数 |
|:---:|-----------|:---:|:---:|
| K1 | 石家庄 | 3 | N |
| K2 | 雄安 | 3 | N |
| K3 | 北京 | 3 | N |
| K4 | 天津 | 3 | N |
| K5 | 河北 | 3 | N |
| K6 | 保定 | 3 | N |
| K7 | 唐山 | 3 | N |
| **合计** | — | **21** | **N** |

---

## 💡 快速解读

- 如果 ⭐⭐⭐ 数量 ≥ 3：今天岗位质量不错，值得手动深挖
- 如果 ⭐⭐⭐ 数量 = 0 但 ⭐⭐ 较多：有候选但需手动核实住宿条件
- 如果匹配总和 < 5：今天市场需求偏冷，可等明天再看

---

*🤖 自动日报 · 快速模式 · {date} 生成*
*⏰ 下次自动运行：明天 08:00（如已配置定时任务）*
```

## ⚠️ 重要约束

- **不要点开链接**（不要用 WebFetch）
- **不要做二次搜索**（就用搜索结果页的摘要文字判断）
- **必须运行 7 次搜索**（一次一个关键词，共 7 次 WebSearch 调用）
- 搜索摘要为空或完全不相关的，跳过不列入
- 如果某个关键词搜索返回 0 条结果，在概况表中如实标记结果数为 0"""


# ============================================================
# 主流程
# ============================================================

def generate_quick_report():
    """调用 Claude Code 生成快速日报（双数据源：WebSearch + jobhunt）"""
    today = datetime.date.today()
    today_str = str(today)
    print(f"⚡ 快速模式：生成 {today_str} 的自动日报...")

    # ----- 步骤 1：采集 jobhunt-cli 数据 -----
    jobhunt_rows = []
    jobhunt_stats = {
        "raw_count": 0, "after_dedup": 0,
        "relevant_count": 0, "injected": 0,
    }
    jobhunt_available = check_jobhunt_available()

    if jobhunt_available:
        print(f"   🔗 jobhunt-cli：采集 {len(JOBHUNT_COMPANIES)} 家大厂官网...")
        all_jh, jh_stats = collect_jobhunt_data()
        jobhunt_stats.update(jh_stats)

        # 相关度过滤 → Top20
        jobhunt_rows, total_relevant = filter_and_rank_jobhunt(all_jh)
        jobhunt_stats["relevant_count"] = total_relevant
        jobhunt_stats["prompt_count"] = len(jobhunt_rows)
        print(f"   🔗 jobhunt：原始 {jh_stats['raw_count']} → 去重 {jh_stats['after_dedup']}"
              f" → 相关 {total_relevant} → Top {len(jobhunt_rows)}")
    else:
        print("   ⚠️ job 命令不可用，仅使用 WebSearch 数据源")

    # ----- 步骤 2：Claude Code WebSearch -----
    prompt = QUICK_SEARCH_PROMPT.replace("{today}", today_str).replace("{date}", today_str)
    print(f"   📌 WebSearch：7组关键词 × 前3条 | 仅看摘要 | 不点链接")

    DESKTOP.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "-p", prompt],
        capture_output=True,
        encoding='utf-8',
        errors='ignore',
        cwd=DESKTOP,
        shell=True,
        timeout=600,
    )

    # 构建报告内容
    raw_body = result.stdout if result.stdout and result.stdout.strip() else ""
    if not raw_body:
        raw_body = "⚠️ **未获取到搜索结果**，请检查网络或搜索关键词。\n\n"

    # ----- 步骤 3：后处理：注入 jobhunt 数据 -----
    if jobhunt_rows:
        injected_body, inj_stats = inject_jobhunt_rows(raw_body, jobhunt_rows)
        if inj_stats:
            raw_body = injected_body
            jobhunt_stats["injected"] = inj_stats["injected"]
            print(f"   🔗 注入 {inj_stats['injected']} 条官方招聘数据到汇总表")
        else:
            print("   🔗 官方招聘数据与 WebSearch 无新增差异")

    # ----- 步骤 4：后处理：去重 -----
    def _print_dedup(st):
        print(f"   📊 去重：{st['before']} → {st['after']}（去除 {st['removed']} 条重复）")
    deduped_body, stats = deduplicate_table(raw_body, print_callback=_print_dedup)

    # ----- 步骤 5：后处理：历史对比 -----
    change_section, change_stats = compare_with_yesterday(deduped_body, report_dir=DESKTOP)
    if change_stats.get("yesterday_date"):
        yl = change_stats["yesterday_date"]
        print(f"   📈 对比昨日（{yl}）："
              f"🆕{change_stats['new_count']} "
              f"❌{change_stats['removed_count']} "
              f"➖{change_stats['unchanged_count']}")

    # ----- 步骤 6：保存日报 -----
    filename = DESKTOP / f"daily_report_{today_str}_自动版.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 📅 智能求职日报（自动版）— {today_str}\n\n")
        f.write(f"> ⚡ **快速模式** | 双数据源：WebSearch + 官方招聘 | 未核实链接详情\n")
        f.write(f"> 🔄 独立于高精度手动模式（\"执行日报任务\"触发）\n")
        f.write(f"> 🕐 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        if jobhunt_available:
            f.write(f"> 🔗 数据源 B：jobhunt-cli 直搜 {jh_stats.get('companies_searched', 8)} 家大厂官网"
                    f"（原始 {jh_stats.get('raw_count', 0)} 条 → 注入 {jobhunt_stats['injected']} 条）\n\n")
        else:
            f.write("> ⚠️ jobhunt-cli 未安装，仅使用 WebSearch 数据源\n\n")
        f.write("---\n\n")

        if change_section:
            f.write(change_section)

        f.write(deduped_body)
        if not result.stdout or not result.stdout.strip():
            f.write("### 可能原因\n")
            f.write("- 网络代理未开启\n")
            f.write("- 搜索 API 暂时不可用\n")
            f.write("- 关键词需要调整\n\n")
            if result.stderr:
                f.write(f"---\n### 错误输出\n```\n{result.stderr[:2000]}\n```\n")

    print(f"✅ 自动日报已保存到：{filename}")
    return filename


if __name__ == "__main__":
    try:
        generate_quick_report()
    except Exception as e:
        print(f"❌ 自动日报生成失败：{e}")
        log_file = DESKTOP / "auto_report_error.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now()}] 错误：{e}\n")
        sys.exit(1)
