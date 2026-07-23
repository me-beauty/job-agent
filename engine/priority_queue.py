#!/usr/bin/env python3
"""
任务优先级队列 — 区分爬虫爬取 / 模型训练 / 浏览器操作权重。

基于 Python stdlib heapq，零外部依赖。

优先级层级:
  PRIORITY_HIGH   (0) — 模型训练 / API 打分
  PRIORITY_MEDIUM (1) — 浏览器搜索 / 投递
  PRIORITY_LOW    (2) — 批量爬虫 / CSV 导出 / 后台抓取

用法:
    from engine.priority_queue import PriorityTaskQueue, PRIORITY_HIGH

    pq = PriorityTaskQueue(max_workers=3)
    pq.enqueue(task_id, PRIORITY_MEDIUM, fn, *args, **kwargs)
    pq.start()
"""

import heapq
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional

from config.settings import settings
from engine.task_manager import TaskManager
from utils.logger import get_logger

logger = get_logger("engine.queue")

PRIORITY_HIGH = 0     # 训练、打分
PRIORITY_MEDIUM = 1   # 浏览器搜索、投递
PRIORITY_LOW = 2      # 爬虫、CSV导出

# 类型映射 → 默认优先级
TYPE_PRIORITY_MAP = {
    "train":  PRIORITY_HIGH,
    "score":  PRIORITY_HIGH,
    "search": PRIORITY_MEDIUM,
    "apply":  PRIORITY_MEDIUM,
    "scrape": PRIORITY_LOW,
    "crawl":  PRIORITY_LOW,
}

MAX_BROWSER_CONCURRENT = 3   # 浏览器任务最大并发
MAX_CRAWL_CONCURRENT = 2     # 爬虫最大并发
MAX_TRAIN_CONCURRENT = 1     # 训练串行执行


@dataclass(order=True)
class _TaskItem:
    priority: int
    enqueue_time: float = field(compare=False)
    task_id: str = field(compare=False)
    fn: Callable = field(compare=False)
    args: tuple = field(compare=False)
    kwargs: dict = field(compare=False)


class PriorityTaskQueue:
    """
    优先级任务队列。

    特征:
      - 高优先级任务优先执行
      - 同优先级 FIFO
      - 浏览器/爬虫/训练各自有并发上限
      - 自动写入 DB 任务状态
    """

    def __init__(self, max_browser: int = None, max_crawl: int = None, max_train: int = None):
        self._queue: list[_TaskItem] = []
        self._lock = threading.Lock()
        self._sem_browser = threading.BoundedSemaphore(max_browser or MAX_BROWSER_CONCURRENT)
        self._sem_crawl = threading.BoundedSemaphore(max_crawl or MAX_CRAWL_CONCURRENT)
        self._sem_train = threading.BoundedSemaphore(max_train or MAX_TRAIN_CONCURRENT)
        self._running: dict[str, threading.Thread] = {}
        self._stopped = False
        self._task_manager = TaskManager()
        logger.info(
            f"PriorityQueue init: browser={max_browser or MAX_BROWSER_CONCURRENT} "
            f"crawl={max_crawl or MAX_CRAWL_CONCURRENT} train={max_train or MAX_TRAIN_CONCURRENT}"
        )

    # ---------- 入队 ----------

    def enqueue(self, task_id: str, priority: int, fn: Callable, *args, **kwargs):
        """
        入队一个任务。

        Args:
            task_id: 任务 ID (str)
            priority: PRIORITY_HIGH / MEDIUM / LOW
            fn: 任务函数
            args, kwargs: 函数参数
        """
        item = _TaskItem(
            priority=priority,
            enqueue_time=time.time(),
            task_id=task_id,
            fn=fn,
            args=args,
            kwargs=kwargs,
        )
        with self._lock:
            heapq.heappush(self._queue, item)
        logger.debug(f"Enqueued: {task_id} pri={priority} size={self.size()}")

    def enqueue_by_type(self, task_id: str, task_type: str, fn: Callable, *args, **kwargs):
        """按 task_type 自动设置优先级"""
        priority = TYPE_PRIORITY_MAP.get(task_type, PRIORITY_LOW)
        self.enqueue(task_id, priority, fn, *args, **kwargs)

    # ---------- 执行 ----------

    def start(self, daemon: bool = True):
        """启动后台消费线程"""
        t = threading.Thread(target=self._worker, daemon=daemon, name="priority-worker")
        t.start()
        logger.info("PriorityQueue worker started")

    def stop(self):
        self._stopped = True

    def _select_sem(self, task_type: str) -> threading.BoundedSemaphore:
        if task_type in ("train", "score"):
            return self._sem_train
        elif task_type in ("search", "apply"):
            return self._sem_browser
        return self._sem_crawl

    def _worker(self):
        """后台消费线程"""
        while not self._stopped:
            item = None
            with self._lock:
                if self._queue:
                    item = heapq.heappop(self._queue)

            if item is None:
                time.sleep(0.2)
                continue

            # 确定任务类型（从 task_id 推断）
            task_type = "unknown"
            for t in TYPE_PRIORITY_MAP:
                if item.task_id.startswith(t):
                    task_type = t
                    break

            sem = self._select_sem(task_type)
            acquired = sem.acquire(timeout=30)
            if not acquired:
                # 重新入队
                with self._lock:
                    heapq.heappush(self._queue, item)
                logger.warning(f"Sem timeout, re-enqueued: {item.task_id}")
                continue

            # Capture locals for thread-safe closure
            _task_id = item.task_id
            _priority = item.priority
            _fn = item.fn
            _args = item.args
            _kwargs = item.kwargs

            def _runner(tid, pri, tp, fn, a, kw):
                try:
                    self._task_manager.update(tid, "running")
                    logger.info(f"Executing: {tid} pri={pri} type={tp}")
                    result = fn(*a, **kw)
                    self._task_manager.update(tid, "done", result)
                    logger.info(f"Done: {tid}")
                except Exception as e:
                    logger.error(f"Task {tid} failed: {e}", exc_info=True)
                    self._task_manager.update(tid, "error", error_msg=str(e))
                finally:
                    sem.release()
                    with self._lock:
                        self._running.pop(tid, None)

            t = threading.Thread(
                target=_runner, daemon=True,
                name=f"task-{_task_id[:20]}",
                args=(_task_id, _priority, task_type, _fn, _args, _kwargs),
            )
            with self._lock:
                self._running[item.task_id] = t
            t.start()

    # ---------- 查询 ----------

    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    def stats(self) -> dict:
        with self._lock:
            return {
                "queued": len(self._queue),
                "running": len(self._running),
                "running_ids": list(self._running.keys())[:10],
            }

    def dump_queue(self) -> list[dict]:
        """导出当前队列（用于调试）"""
        with self._lock:
            items = sorted(self._queue, key=lambda x: x.priority)
            return [{"task_id": i.task_id, "priority": i.priority,
                     "waited_sec": round(time.time() - i.enqueue_time, 1)} for i in items]


# 全局单例
_pq_instance: Optional[PriorityTaskQueue] = None


def get_queue() -> PriorityTaskQueue:
    global _pq_instance
    if _pq_instance is None:
        _pq_instance = PriorityTaskQueue()
        _pq_instance.start()
    return _pq_instance
