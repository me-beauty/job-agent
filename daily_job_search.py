#!/usr/bin/env python3
"""
智能求职日报Agent - 自动搜索脚本
每天早上运行，生成当日实习推荐日报
"""

import subprocess
import datetime
import os
import sys
import io
from pathlib import Path

# 共享工具（去重 + 历史对比 + jobhunt）
from report_utils import (
    deduplicate_table, compare_with_yesterday,
    check_jobhunt_available, collect_jobhunt_data,
    filter_and_rank_jobhunt, inject_jobhunt_rows,
    JOBHUNT_COMPANIES,
)

# 强制 stdout 使用 UTF-8，解决中文 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

# 桌面路径（你的项目文件夹）
DESKTOP = Path.home() / "Desktop" / "job_agent"

# 你的搜索指令
SEARCH_PROMPT = """请搜索2027届本科数据科学相关实习岗位，要求：
1. 地点：河北省内（石家庄、保定、唐山、廊坊、雄安等）及周边（北京、天津、山东、河南、山西靠近河北的城市），远程实习也可
2. 周末双休
3. 提供住宿或住宿补贴
4. 有实习工资
5. 无销售性质
6. 实习时长4个月以上

地点标注规则：
- 河北省内 → 标注"省内"
- 北京/天津 → 标注"周边（需住宿）"
- 其他周边省份 → 标注"周边其他"
- 远程 → 标注"远程"

请按以下格式输出日报：
### 一、岗位汇总表
表格列：公司、岗位、地点（含标注）、住宿情况、薪资、双休、2027届、匹配度

### 二、TOP 3 推荐
每个写3行推荐理由，重点说匹配点

### 三、投递优先级建议
按省内、周边（有住宿）、周边（无住宿）、远程排序

搜索来源：实习僧、牛客网、各公司官网、国聘网
"""

def generate_daily_report():
    """调用Claude Code生成精准日报（双数据源）"""
    today = datetime.date.today()
    print(f"🚀 精准模式：开始生成 {today} 的实习日报...")

    # ----- 步骤 1：采集 jobhunt-cli 数据 -----
    jobhunt_rows = []
    jobhunt_stats = {"raw_count": 0, "injected": 0}
    jobhunt_available = check_jobhunt_available()

    if jobhunt_available:
        print(f"   🔗 jobhunt-cli：采集 {len(JOBHUNT_COMPANIES)} 家大厂官网...")
        all_jh, jh_stats = collect_jobhunt_data()
        jobhunt_stats.update(jh_stats)

        jobhunt_rows, total_relevant = filter_and_rank_jobhunt(all_jh)
        jobhunt_stats["relevant_count"] = total_relevant
        print(f"   🔗 jobhunt：原始 {jh_stats['raw_count']} → 去重 {jh_stats['after_dedup']}"
              f" → 相关 {total_relevant} → Top {len(jobhunt_rows)}")
    else:
        print("   ⚠️ job 命令不可用，仅使用 WebSearch 数据源")

    # ----- 步骤 2：Claude Code 高精度搜索 -----
    DESKTOP.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "-p", SEARCH_PROMPT],
        capture_output=True,
        encoding='utf-8',
        errors='ignore',
        cwd=DESKTOP,
        shell=True,
    )

    raw_body = result.stdout if result.stdout and result.stdout.strip() else ""
    if not raw_body:
        raw_body = "⚠️ 未获取到搜索结果，请检查网络或搜索关键词。\n\n"

    # ----- 步骤 3：后处理：注入 jobhunt 数据 -----
    if jobhunt_rows:
        injected_body, inj_stats = inject_jobhunt_rows(raw_body, jobhunt_rows)
        if inj_stats:
            raw_body = injected_body
            jobhunt_stats["injected"] = inj_stats["injected"]
            print(f"   🔗 注入 {inj_stats['injected']} 条官方招聘数据到汇总表")

    # ----- 步骤 4：后处理：去重 -----
    def _print_dedup(st):
        print(f"   📊 去重：{st['before']} → {st['after']}（去除 {st['removed']} 条重复）")
    deduped_body, stats = deduplicate_table(raw_body, print_callback=_print_dedup)

    # ----- 步骤 5：后处理：历史对比 -----
    change_section, change_stats = compare_with_yesterday(deduped_body, report_dir=DESKTOP)
    if change_stats.get("yesterday_date"):
        yl = change_stats["yesterday_date"]
        print(f"   📈 对比昨日（{yl}）：🆕{change_stats['new_count']} ❌{change_stats['removed_count']} ➖{change_stats['unchanged_count']}")

    # ----- 步骤 6：保存日报 -----
    filename = DESKTOP / f"daily_report_{today}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 📅 智能求职日报 - {today}\n\n")
        if jobhunt_available:
            f.write(f"> 🔗 数据源 B：jobhunt-cli 直搜 {jh_stats.get('companies_searched', 8)} 家大厂官网"
                    f"（注入 {jobhunt_stats['injected']} 条官方招聘数据）\n\n")
        if change_section:
            f.write(change_section)
        f.write(deduped_body)
        if not result.stdout or not result.stdout.strip():
            if result.stderr:
                f.write(f"\n---\n### 错误信息\n```\n{result.stderr[:2000]}\n```\n")

    print(f"✅ 日报已保存到：{filename}")
    return filename

if __name__ == "__main__":
    generate_daily_report()