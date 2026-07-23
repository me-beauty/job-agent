#!/usr/bin/env python3
"""LLM 工厂 — Claude / DeepSeek 统一创建接口"""

import os
from typing import Any
from dotenv import load_dotenv
load_dotenv()


def create_llm(provider: str = None) -> Any:
    """
    创建 LLM 实例，支持 claude / deepseek。

    Args:
        provider: "claude" (默认) 或 "deepseek"

    Returns:
        browser-use compatible ChatModel instance

    Raises:
        RuntimeError: 缺少对应 API Key
        ValueError: 不支持的 provider
    """
    if provider is None:
        provider = os.environ.get("JOB_AGENT_LLM", "claude")

    provider = provider.lower()

    if provider == "claude":
        return _create_claude()
    elif provider == "deepseek":
        return _create_deepseek()
    else:
        raise ValueError(f"不支持的 LLM provider: {provider}，可选：claude / deepseek")


def _create_claude():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 环境变量未设置")

    try:
        from browser_use import ChatAnthropic
    except ImportError:
        from browser_use.llm.anthropic.chat import ChatAnthropic

    return ChatAnthropic(model="claude-sonnet-4-6", api_key=api_key)


def _create_deepseek():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 环境变量未设置")

    try:
        from browser_use import ChatOpenAI
    except ImportError:
        from browser_use.llm.openai.chat import ChatOpenAI

    return ChatOpenAI(model="deepseek-chat", api_key=api_key, base_url="https://api.deepseek.com/v1")
