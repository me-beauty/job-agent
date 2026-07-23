#!/usr/bin/env python3
"""
岗位搜索 — 求职业务插件，依赖 engine.BrowserController。

用法:
    from business.job_search import search_jobs_async
    results = await search_jobs_async("数据科学实习", city="石家庄")
"""

import asyncio
import json
import os
import sys

# ---- Windows async subprocess fix for browser-use ----
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from engine.browser_controller import BrowserController
from engine.llm_factory import create_llm
from utils.browser_anti_detect import random_delay
from utils.logger import get_logger

logger = get_logger("business.search")

# 招聘网站配置
JOB_SITES = {
    "shixiseng": {"name": "实习僧", "search_url": "https://www.shixiseng.com/interns?keyword={keyword}&city={city}"},
    "nowcoder":  {"name": "牛客网", "search_url": "https://www.nowcoder.com/jobs/recommend?query={keyword}"},
    "zhipin":    {"name": "BOSS直聘", "search_url": "https://www.zhipin.com/web/geek/job?query={keyword}"},
    "guopin":    {"name": "国聘网", "search_url": "https://www.iguopin.com/search?keyword={keyword}"},
    "lagou":     {"name": "拉勾网", "search_url": "https://www.lagou.com/wn/jobs?kd={keyword}"},
}

CITY_MAP = {"石家庄": "石家庄", "保定": "保定", "唐山": "唐山", "雄安": "雄安新区",
            "北京": "北京", "天津": "天津", "廊坊": "廊坊"}


async def search_jobs_async(
    keyword: str,
    sites: list = None,
    city: str = "石家庄",
    max_per_site: int = 5,
    llm_provider: str = None,
) -> list[dict]:
    """异步搜索岗位"""
    if sites is None:
        sites = ["shixiseng", "nowcoder"]

    llm = create_llm(llm_provider)
    all_jobs = []

    for site_key in sites:
        site = JOB_SITES.get(site_key)
        if not site:
            logger.warning(f"Unknown site: {site_key}")
            continue

        random_delay(1, 3)
        search_url = site["search_url"].format(keyword=keyword, city=CITY_MAP.get(city, city))

        task = f"""你是求职搜索助手。
1. 打开: {search_url}
2. 等页面加载（3秒）
3. 滚动浏览岗位列表
4. 提取最多 {max_per_site} 个岗位: company, position, location, salary, date, url
5. 用 final_result 返回 JSON 数组"""

        try:
            ctrl = BrowserController(llm_provider=llm_provider)
            result = await ctrl.run_agent(task, llm=llm)
            jobs = _parse_json(result.get("final_result", ""))
            for j in jobs:
                j["source"] = site["name"]; j["search_keyword"] = keyword
            all_jobs.extend(jobs)
            logger.info(f"{site['name']}: {len(jobs)} jobs")
        except Exception as e:
            logger.error(f"Search {site_key} failed: {e}")
        finally:
            ctrl.teardown()

    return all_jobs


def search_jobs_sync(keyword, sites=None, city="石家庄", llm_provider=None) -> list[dict]:
    """同步版搜索（供 Flask 调用）"""
    try:
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(search_jobs_async(keyword, sites, city, llm_provider=llm_provider))
    except RuntimeError:
        return asyncio.run(search_jobs_async(keyword, sites, city, llm_provider=llm_provider))


def _parse_json(text: str) -> list[dict]:
    if not text: return []
    try:
        d = json.loads(text)
        return d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
    except json.JSONDecodeError:
        import re
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            try: return json.loads(m.group())
            except: pass
        return []
