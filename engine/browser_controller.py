#!/usr/bin/env python3
"""浏览器控制器 — 封装 browser-use 的浏览器生命周期"""

import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from config.settings import settings
from utils.logger import get_logger
from utils.browser_anti_detect import random_ua, random_window_size

logger = get_logger("engine.browser")


class BrowserController:
    """
    通用浏览器操控封装。不依赖求职业务。

    用法:
        ctrl = BrowserController()
        await ctrl.run_agent(task_prompt, llm)
        await ctrl.teardown()
    """

    def __init__(self, headless: bool = None, llm_provider: str = None):
        """
        Args:
            headless: True=无头模式，默认从 settings 读取
            llm_provider: "claude" 或 "deepseek"
        """
        self.headless = headless if headless is not None else settings.BROWSER_HEADLESS
        self.llm_provider = llm_provider or settings.JOB_AGENT_LLM
        self._browser = None

    def _get_browser(self):
        """懒加载浏览器实例"""
        try:
            from browser_use import Browser
        except ImportError:
            from browser_use.browser import Browser

        kwargs = {"headless": self.headless, "enable_default_extensions": False}
        if settings.BROWSER_ANTI_DETECT:
            w, h = random_window_size()
            ua = random_ua()
            try:
                kwargs["viewport"] = {"width": w, "height": h}
                kwargs["user_agent"] = ua
            except Exception:
                pass  # 某些版本不支持这些参数

        self._browser = Browser(**kwargs)
        logger.info(f"Browser launched (headless={self.headless})")
        return self._browser

    async def run_agent(self, task: str, llm=None, max_steps: int = 30) -> dict:
        """
        执行一个浏览器任务。

        Args:
            task: 任务描述 prompt
            llm: ChatModel 实例（不传则自动创建）
            max_steps: 最大步数

        Returns:
            {"success": bool, "final_result": str, "history": ...}
        """
        if llm is None:
            from engine.llm_factory import create_llm
            llm = create_llm(self.llm_provider)

        try:
            from browser_use import Agent
        except ImportError:
            raise ImportError("browser-use 未安装: pip install browser-use")

        browser = self._get_browser()
        agent = Agent(task=task, llm=llm, browser=browser)
        history = await agent.run()

        logger.info(f"Agent task completed: {task[:60]}...")
        return {"success": True, "final_result": history.final_result(), "history": history}

    def teardown(self):
        """关闭浏览器，释放资源"""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
            logger.info("Browser closed")

    def __del__(self):
        self.teardown()
