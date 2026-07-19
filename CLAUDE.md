# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a personal job-search automation tool that generates daily internship recommendation reports. It uses Claude Code itself (`claude -p`) as the search and report-generation backend, invoked either programmatically via Python or interactively via a Windows batch file.

The target user is a 2027 (2023-entry) undergraduate in Data Science & Big Data Technology, seeking internships in Hebei Province and surrounding areas.

## Two independent report modes

### Mode 1: High-precision (manual trigger)

Triggered by saying **"执行日报任务"** in Claude Code. Opens links, verifies details, produces comprehensive reports with TOP 3 deep analysis, application strategy, and HR question scripts.

- **Script**: `daily_job_search.py` (headless) or `启动日报Agent.bat` (interactive)
- **Prompt source**: `SEARCH_PROMPT` constant in `daily_job_search.py` and `一键搜索.md` (keep in sync)
- **Output**: `daily_report_YYYY-MM-DD.md`
- **Search depth**: Opens links via WebFetch, verifies details, multi-round search
- **Key criteria**: 2027届数据科学本科 / 河北及周边 / 双休 / 住宿或补贴 / 有工资 / 无销售 / 4个月+

### Mode 2: Quick auto (scheduled, runs daily at 08:00)

Fully independent from Mode 1. Triggered by Windows Task Scheduler. Only reads search result snippets — no link opening, no verification.

- **Script**: `daily_job_search_quick.py`
- **Batch wrapper**: `启动自动日报.bat`
- **Scheduler setup**: Run `安装定时任务.bat` as Administrator (or `安装定时任务.ps1`)
- **Task name in Task Scheduler**: `JobAgent_AutoDailyReport`
- **Output**: `daily_report_YYYY-MM-DD_自动版.md` (separate from high-precision output)
- **Search**: 7 fixed keywords × top 3 results each = max 21 items
- **Filtering**: Matches snippet text against 双休/住宿/薪资 keywords
- **Matching tiers**: ⭐⭐⭐ (all 3) / ⭐⭐ (2) / ⭐ (1)
- **No WebFetch** — relies entirely on search snippet text

### Managing the scheduled task

```powershell
# View task
Get-ScheduledTask -TaskName "JobAgent_AutoDailyReport" | Select-Object State

# Run now (test)
Start-ScheduledTask -TaskName "JobAgent_AutoDailyReport"

# Delete task
Unregister-ScheduledTask -TaskName "JobAgent_AutoDailyReport" -Confirm:$false
```

Or open `taskschd.msc` and search for `JobAgent_AutoDailyReport`.

## Output format

High-precision reports (`daily_report_YYYY-MM-DD.md`) contain:
1. User profile summary
2. Key findings / honest market reality check
3. Full results table with per-condition columns
4. TOP 3 detailed recommendations with rationale
5. Other candidates ranked with pros/cons (up to 10-12)
6. Condition comparison matrix
7. Application strategy by priority tier
8. Channels/links for each company
9. Questions to ask HR
10. Items needing manual verification

Quick reports (`daily_report_YYYY-MM-DD_自动版.md`) contain:
1. Summary table with 双休/住宿/薪资 checkmarks and ⭐ match rating
2. Grouped by match tier (⭐⭐⭐ / ⭐⭐ / ⭐)
3. Per-keyword search stats

## Windows encoding note

The Python script overrides `sys.stdout` to use UTF-8 because Windows defaults to GBK, which fails on CJK characters in Claude's output. Both `subprocess.run` and file writes use `encoding='utf-8', errors='ignore'`.
