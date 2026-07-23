#!/usr/bin/env python3
"""
浏览器防反爬工具 — 随机 UA / 延迟 / 窗口 / 分片 / captcha 检测。

用法:
  from utils.browser_anti_detect import random_ua, random_delay, chunk_tasks

  random_delay(1, 3)                # sleep 1~3 秒
  ua = random_ua()                  # 随机 User-Agent
  w, h = random_window_size()       # 随机窗口尺寸
  for batch in chunk_tasks(items):  # 分片迭代
      process(batch)
"""

import random
import time
from typing import Iterator

RANDOM_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/116.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

WINDOW_SIZES = [
    (1920, 1080), (1680, 1050), (1600, 900), (1440, 900),
    (1366, 768), (1536, 864), (1920, 1200),
]

CAPTCHA_KEYWORDS = [
    "验证码", "captcha", "verify", "人机验证", "slider",
    "请完成安全验证", "点击验证", "请拖动滑块",
    "are you a robot", "security check", "press and hold",
]


def random_ua() -> str:
    """随机 User-Agent"""
    return random.choice(RANDOM_UA)


def random_delay(min_s: float = 1.0, max_s: float = 5.0):
    """随机延迟"""
    time.sleep(random.uniform(min_s, max_s))


def random_window_size() -> tuple:
    """随机窗口尺寸"""
    return random.choice(WINDOW_SIZES)


def chunk_tasks(items: list, max_per_chunk: int = 5) -> Iterator[list]:
    """分片迭代，防止一次性大批量请求"""
    for i in range(0, len(items), max_per_chunk):
        yield items[i:i + max_per_chunk]


def detect_captcha(page_text: str) -> bool:
    """检测页面是否出现人机验证"""
    lower = page_text.lower()
    return any(kw in lower for kw in CAPTCHA_KEYWORDS)


def should_pause_on_captcha(page_text: str) -> bool:
    """遇到验证码时返回 True"""
    if detect_captcha(page_text):
        return True
    return False
