#!/usr/bin/env python3
"""
简易令牌桶限流器 — 无需外部依赖。

用法:
  limiter = TokenBucket(rate=5, capacity=10)  # 每秒 5 个, 最大 10
  if limiter.consume():
      ...  # 放行
  else:
      return 429

Flask 集成 (web_server.py):
  RATE_LIMITS = {
      "/api/train_match_model": TokenBucket(rate=0.017, capacity=1),   # 1/min
      "/api/search":            TokenBucket(rate=0.083, capacity=5),   # 5/min
      "/api/apply":             TokenBucket(rate=0.083, capacity=5),
      "/api/scrape":            TokenBucket(rate=0.083, capacity=5),
  }
  DEFAULT_LIMIT = TokenBucket(rate=0.33, capacity=20)  # 20/min
"""

import time
import threading


class TokenBucket:
    """令牌桶限流器"""

    def __init__(self, rate: float = 10.0, capacity: float = 20.0):
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max tokens
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        with self.lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self.lock:
            self._refill()
            return self.tokens


# 预定义限流器注册表
_limits: dict[str, TokenBucket] = {}
_limits_lock = threading.Lock()

_DEFAULT_LIMIT = TokenBucket(rate=0.33, capacity=20)  # 20/min default


def get_limiter(path: str) -> TokenBucket:
    """按路径前缀匹配限流器"""
    with _limits_lock:
        # Exact match first
        if path in _limits:
            return _limits[path]
        # Prefix match
        for prefix, bucket in sorted(_limits.items(), key=lambda x: -len(x[0])):
            if path.startswith(prefix):
                return bucket
        return _DEFAULT_LIMIT


def register_limiter(path: str, rate: float, capacity: float):
    """注册限流规则"""
    with _limits_lock:
        _limits[path] = TokenBucket(rate=rate, capacity=capacity)


# 默认注册
register_limiter("/api/train_match_model", rate=0.017, capacity=1)   # 1/min
register_limiter("/api/search",            rate=0.083, capacity=5)   # 5/min
register_limiter("/api/apply",             rate=0.083, capacity=5)
register_limiter("/api/scrape",            rate=0.083, capacity=5)
