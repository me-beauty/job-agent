#!/usr/bin/env python3
"""
Job Browser Agent — 基于 browser-use 的浏览器自动化求职模块

提供 3 个核心能力：
  search_jobs()   — 自动检索招聘网站岗位
  apply_to_job()  — 自动填写投递表单
  scrape_to_csv() — 抓取岗位列表导出 CSV

LLM 后端支持 Claude + DeepSeek 双模型自动切换。

Usage:
  # 作为库使用
  from job_browser import JobBrowserAgent
  agent = JobBrowserAgent(llm_provider="claude")  # or "deepseek"
  results = await agent.search_jobs("数据科学实习", sites=["shixiseng", "nowcoder"])

  # 命令行测试
  python job_browser.py search --keyword "数据分析实习" --site shixiseng
  python job_browser.py apply --url "https://..." --resume resume.pdf
  python job_browser.py scrape --url "https://..." --output jobs.csv
"""

import asyncio
import csv
import datetime
import io
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

# Windows GBK 编码适配
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

from dotenv import load_dotenv
load_dotenv()

from utils.browser_anti_detect import random_delay, random_ua, random_window_size, chunk_tasks, should_pause_on_captcha
from utils.logger import get_logger

logger = get_logger("browser")

# ============================================================
# LLM 工厂：Claude + DeepSeek 双模型
# ============================================================

def _get_llm(provider: str = "claude"):
    """
    获取 LLM 实例。支持 claude / deepseek。
    从环境变量读取 API Key。
    """
    provider = provider.lower()

    if provider == "claude":
        try:
            from browser_use import ChatAnthropic
        except ImportError:
            from browser_use.llm.anthropic.chat import ChatAnthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY 环境变量未设置")
        return ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=api_key,
        )

    elif provider == "deepseek":
        try:
            from browser_use import ChatOpenAI
        except ImportError:
            from browser_use.llm.openai.chat import ChatOpenAI
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 环境变量未设置")
        return ChatOpenAI(
            model="deepseek-chat",
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )

    else:
        raise ValueError(f"不支持的 LLM provider: {provider}，可选：claude / deepseek")


# ============================================================
# 招聘网站配置
# ============================================================

JOB_SITES = {
    "shixiseng": {
        "name": "实习僧",
        "search_url": "https://www.shixiseng.com/interns?keyword={keyword}&city={city}",
        "type": "intern",
        "note": "需要处理反爬，建议用 browser-use 真实浏览器",
    },
    "nowcoder": {
        "name": "牛客网",
        "search_url": "https://www.nowcoder.com/jobs/recommend?query={keyword}",
        "type": "fulltime+intern",
    },
    "zhipin": {
        "name": "BOSS直聘",
        "search_url": "https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}",
        "type": "fulltime+intern",
    },
    "guopin": {
        "name": "国聘网",
        "search_url": "https://www.iguopin.com/search?keyword={keyword}",
        "type": "fulltime+intern",
    },
    "lagou": {
        "name": "拉勾网",
        "search_url": "https://www.lagou.com/wn/jobs?kd={keyword}",
        "type": "fulltime+intern",
    },
}

# 城市映射 (实习僧 city 参数)
CITY_MAP = {
    "石家庄": "石家庄",
    "保定": "保定",
    "唐山": "唐山",
    "雄安": "雄安新区",
    "北京": "北京",
    "天津": "天津",
    "廊坊": "廊坊",
}


# ============================================================
# JobBrowserAgent — 核心类
# ============================================================

class JobBrowserAgent:
    """基于 browser-use 的求职浏览器自动化 Agent"""

    def __init__(self, llm_provider: str = "claude", headless: bool = False):
        """
        Args:
            llm_provider: "claude" 或 "deepseek"
            headless: 是否无头模式（True=后台运行）
        """
        self.llm_provider = llm_provider
        self.headless = headless
        self._llm = None
        self._last_result = None

    def _get_browser(self):
        """创建 Browser 实例"""
        try:
            from browser_use import Browser
        except ImportError:
            from browser_use.browser import Browser
        return Browser(headless=self.headless)

    @property
    def llm(self):
        """延迟初始化 LLM"""
        if self._llm is None:
            self._llm = _get_llm(self.llm_provider)
        return self._llm

    # ---------- 核心能力 1：搜索岗位 ----------

    async def search_jobs(
        self,
        keyword: str,
        sites: list = None,
        city: str = "石家庄",
        max_per_site: int = 5,
    ) -> list[dict]:
        """
        在多个招聘网站自动搜索岗位。

        Args:
            keyword: 搜索关键词，如 "数据科学实习"
            sites: 目标网站列表，默认 ["shixiseng", "nowcoder"]
            city: 目标城市
            max_per_site: 每个网站最多提取条数

        Returns:
            list[dict]: 结构化岗位列表
        """
        if sites is None:
            sites = ["shixiseng", "nowcoder"]

        try:
            from browser_use import Agent
        except ImportError:
            raise ImportError("请先安装 browser-use: pip install browser-use")

        all_jobs = []

        for site_key in sites:
            site = JOB_SITES.get(site_key)
            if not site:
                print(f"  ⚠️ Unknown site: {site_key}, skip")
                continue

            # Anti-detect: random delay between sites
            random_delay(1, 3)

            search_url = site["search_url"].format(
                keyword=keyword,
                city=CITY_MAP.get(city, city),
                city_code="",  # BOSS 直聘需要数字 city_code，此处留空
            )

            task = f"""你是一个求职搜索助手。请完成以下任务：

1. 打开网址: {search_url}
2. 等待页面加载完成（至少等 3 秒）
3. 滚动浏览岗位列表
4. 从列表中提取最多 {max_per_site} 个岗位，每个岗位包含：
   - 公司名称
   - 岗位名称
   - 工作地点
   - 薪资范围（如有）
   - 发布时间
   - 岗位链接
5. 输出结果时，使用 final_result，以 JSON 数组格式返回，每个元素包含 company, position, location, salary, date, url 字段。

⚠️ 重要：
- 如果遇到登录弹窗或验证码，关闭弹窗继续
- 如果页面需要点击才能展开列表，点击展开
- 只提取搜索结果列表中的岗位，不要点进详情页"""

            print(f"  🔍 搜索 {site['name']} ...")
            try:
                browser = self._get_browser()
                agent = Agent(
                    task=task,
                    llm=self.llm,
                    browser=browser,
                )
                history = await agent.run()
                result_text = history.final_result()

                # 解析结果
                jobs = self._parse_json_result(result_text, site_key)
                for j in jobs:
                    j["source"] = site["name"]
                    j["search_keyword"] = keyword
                all_jobs.extend(jobs)
                print(f"     ✅ {site['name']} 获取 {len(jobs)} 条")

            except Exception as e:
                print(f"     ❌ {site['name']} 搜索失败: {e}")
                continue

        self._last_result = all_jobs
        return all_jobs

    # ---------- 核心能力 2：自动投递 ----------

    async def apply_to_job(
        self,
        job_url: str,
        resume_path: str = None,
        applicant_info: dict = None,
    ) -> dict:
        """
        打开岗位投递页面，自动填写表单并提交。

        Args:
            job_url: 岗位投递页面 URL
            resume_path: 简历文件路径（PDF）
            applicant_info: 申请人信息 dict，覆盖 resume_template.json

        Returns:
            dict: {"success": bool, "message": str, "screenshot": str}
        """
        try:
            from browser_use import Agent
        except ImportError:
            raise ImportError("请先安装 browser-use: pip install browser-use")

        # 加载简历模板
        template_path = Path(__file__).parent / "resume_template.json"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                info = json.load(f)
        else:
            info = {}

        if applicant_info:
            # 深度合并
            for section in applicant_info:
                if section in info and isinstance(info[section], dict):
                    info[section].update(applicant_info[section])
                else:
                    info[section] = applicant_info[section]

        personal = info.get("personal", {})
        education = info.get("education", {})
        prefs = info.get("job_prefs", {})

        info_text = json.dumps(info, ensure_ascii=False, indent=2)
        has_resume = resume_path and os.path.exists(resume_path)

        task = f"""你是一个求职助手。请帮我填写并提交一个实习岗位申请。

岗位链接: {job_url}

我的信息（JSON）:
{info_text}

{'简历文件路径: ' + resume_path if has_resume else '（无简历文件，手动填写教育/技能信息）'}

操作步骤:
1. 打开 {job_url}
2. 等待页面完全加载
3. 仔细阅读表单每个字段的标签，逐个填写:
   - 姓名: {personal.get('last_name', '')}{personal.get('first_name', '')}
   - 邮箱: {personal.get('email', '')}
   - 电话: {personal.get('phone', '')}
   - 所在城市: {personal.get('city', '')}
   - 学校: {education.get('school', '')}
   - 专业: {education.get('major', '')}
   - 毕业年份: {education.get('grad_year', '')}
   - 到岗时间: {prefs.get('available_start', '')}
   - 实习时长: {prefs.get('duration_months', '')} 个月
   - 每周出勤: {prefs.get('work_days_per_week', '')} 天
   {'- 上传简历: ' + resume_path if has_resume else '- 用 skills 信息填写技能栏: ' + ', '.join(info.get('skills', []))}
4. 填写完所有必填字段后，截图确认。
5. ⚠️ 不要提交！只截图确认即可（这是自动测试）。
6. 用 final_result 报告：哪些字段成功填写了，哪些找不到或有问题。

⚠️ 重要:
- 如果遇到登录弹窗，不要登录，关闭弹窗继续
- 不要跳过任何可见的必填字段
- 下拉框选择请根据上下文选择最合适的选项"""

        print(f"  📝 开始投递: {job_url}")
        try:
            browser = self._get_browser()
            agent = Agent(
                task=task,
                llm=self.llm,
                browser=browser,
            )
            history = await agent.run()
            result_text = history.final_result()

            return {
                "success": True,
                "message": "表单填写完成（未实际提交）",
                "detail": result_text,
                "url": job_url,
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"投递失败: {str(e)}",
                "url": job_url,
            }

    # ---------- 核心能力 3：抓取导出 CSV ----------

    async def scrape_to_csv(
        self,
        url: str,
        output_path: str = None,
        selectors: str = None,
        max_items: int = 20,
    ) -> str:
        """
        从招聘网站抓取岗位列表，导出 CSV。

        Args:
            url: 目标页面 URL
            output_path: CSV 输出路径（默认自动生成）
            selectors: CSS 选择器提示（可选，帮助 LLM 定位列表容器）
            max_items: 最多抓取条数

        Returns:
            str: CSV 文件路径
        """
        try:
            from browser_use import Agent
        except ImportError:
            raise ImportError("请先安装 browser-use: pip install browser-use")

        if output_path is None:
            today = datetime.date.today().strftime("%Y%m%d")
            output_path = str(Path.cwd() / f"jobs_export_{today}.csv")

        selector_hint = ""
        if selectors:
            selector_hint = f"\n建议关注这些 CSS 选择器: {selectors}"

        task = f"""你是一个数据采集助手。请完成以下任务:

1. 打开网址: {url}
2. 等待页面加载完成（等 3-5 秒）
3. 滚动浏览岗位列表，提取最多 {max_items} 个岗位
4. 每个岗位提取以下字段:
   - title: 岗位名称
   - company: 公司名称
   - location: 工作地点
   - salary: 薪资（如有）
   - date: 发布日期（如有）
   - link: 详情链接（如有）
   - tags: 标签/要求（如有）
5. 输出时，使用 final_result，返回一个 JSON 数组，每个元素是一个岗位对象。

⚠️:
- 如果有多页，只抓第 1 页
- 不要点进每个岗位的详情页
- 遇到弹窗关闭它
- 提取不到信息的字段设为空字符串 ""{selector_hint}"""

        print(f"  📊 抓取: {url}")
        try:
            browser = self._get_browser()
            agent = Agent(
                task=task,
                llm=self.llm,
                browser=browser,
            )
            history = await agent.run()
            result_text = history.final_result()

            # 解析 → 写 CSV
            jobs = self._parse_json_result(result_text, "scrape")

            if jobs:
                self._write_csv(jobs, output_path)
                print(f"     ✅ 导出 {len(jobs)} 条 → {output_path}")
            else:
                # 创建空 CSV 带表头
                self._write_csv([], output_path)
                print(f"     ⚠️ 未提取到数据，创建空 CSV: {output_path}")

            return output_path

        except Exception as e:
            print(f"     ❌ 抓取失败: {e}")
            self._write_csv([], output_path)
            return output_path

    # ---------- 工具方法 ----------

    @staticmethod
    def _parse_json_result(result_text: str, source: str = "") -> list[dict]:
        """从 Agent 返回的文本中提取 JSON 数组"""
        if not result_text:
            return []

        text = result_text.strip()

        # 尝试直接解析
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # 可能被包了一层
                for v in data.values():
                    if isinstance(v, list):
                        return v
                return [data]
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 数组
        import re
        # 找最长的 [...] 数组
        matches = list(re.finditer(r'\[.*\]', text, re.DOTALL))
        if matches:
            # 取最长的匹配
            longest = max(matches, key=lambda m: len(m.group()))
            try:
                return json.loads(longest.group())
            except json.JSONDecodeError:
                pass

        # 找 {...} 对象
        obj_matches = list(re.finditer(r'\{[^{}]*\}', text, re.DOTALL))
        if obj_matches:
            results = []
            for m in obj_matches:
                try:
                    results.append(json.loads(m.group()))
                except json.JSONDecodeError:
                    continue
            if results:
                return results

        print(f"     ⚠️ 无法解析结果 JSON，原始返回: {text[:200]}...")
        return []

    @staticmethod
    def _write_csv(jobs: list[dict], path: str):
        """写 CSV 文件（UTF-8 BOM，Excel 友好）"""
        if not jobs:
            fieldnames = ["title", "company", "location", "salary", "date", "link", "tags", "source", "search_keyword"]
        else:
            # 收集所有字段
            fieldnames = []
            seen = set()
            for j in jobs:
                for k in j:
                    if k not in seen:
                        fieldnames.append(k)
                        seen.add(k)

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for j in jobs:
                writer.writerow(j)


# ============================================================
# 便捷的同步包装函数（供 Flask 路由调用）
# ============================================================

def run_async(coro):
    """在同步环境中运行 async 函数"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已有事件循环，用 nest_asyncio（如果安装了）
        try:
            import nest_asyncio
            nest_asyncio.apply()
        except ImportError:
            pass
        return loop.run_until_complete(coro)
    else:
        return asyncio.run(coro)


def search_jobs_sync(keyword, sites=None, city="石家庄", llm_provider="claude"):
    """同步版搜索"""
    agent = JobBrowserAgent(llm_provider=llm_provider)
    return run_async(agent.search_jobs(keyword, sites=sites, city=city))


def scrape_to_csv_sync(url, output_path=None, llm_provider="claude"):
    """同步版抓取"""
    agent = JobBrowserAgent(llm_provider=llm_provider)
    return run_async(agent.scrape_to_csv(url, output_path=output_path))


# ============================================================
# CLI 入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Job Browser Agent - 浏览器自动化求职工具")
    sub = parser.add_subparsers(dest="cmd")

    # search
    p_search = sub.add_parser("search", help="搜索岗位")
    p_search.add_argument("--keyword", "-k", required=True, help="搜索关键词")
    p_search.add_argument("--site", "-s", default="shixiseng", help="目标网站")
    p_search.add_argument("--city", "-c", default="石家庄", help="城市")
    p_search.add_argument("--llm", default="claude", choices=["claude", "deepseek"])

    # apply
    p_apply = sub.add_parser("apply", help="投递岗位")
    p_apply.add_argument("--url", "-u", required=True, help="投递页面 URL")
    p_apply.add_argument("--resume", "-r", help="简历 PDF 路径")
    p_apply.add_argument("--llm", default="claude", choices=["claude", "deepseek"])

    # scrape
    p_scrape = sub.add_parser("scrape", help="抓取导出 CSV")
    p_scrape.add_argument("--url", "-u", required=True, help="目标页面 URL")
    p_scrape.add_argument("--output", "-o", help="CSV 输出路径")
    p_scrape.add_argument("--selector", help="CSS 选择器提示")
    p_scrape.add_argument("--llm", default="claude", choices=["claude", "deepseek"])

    args = parser.parse_args()

    if args.cmd == "search":
        agent = JobBrowserAgent(llm_provider=args.llm)
        sites = [s.strip() for s in args.site.split(",")]
        results = asyncio.run(agent.search_jobs(args.keyword, sites=sites, city=args.city))
        print(f"\n📋 共找到 {len(results)} 个岗位:")
        for i, j in enumerate(results, 1):
            print(f"  {i}. [{j.get('source', '')}] {j.get('company', '?')} — {j.get('position', '?')} | {j.get('location', '?')} | {j.get('salary', '?')}")

    elif args.cmd == "apply":
        agent = JobBrowserAgent(llm_provider=args.llm)
        result = asyncio.run(agent.apply_to_job(args.url, resume_path=args.resume))
        print(f"\n📝 投递结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

    elif args.cmd == "scrape":
        agent = JobBrowserAgent(llm_provider=args.llm)
        path = asyncio.run(agent.scrape_to_csv(args.url, output_path=args.output, selectors=args.selector))
        print(f"\n📊 CSV 已保存: {path}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
