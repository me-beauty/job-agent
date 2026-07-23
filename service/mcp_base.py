#!/usr/bin/env python3
"""
通用 MCP Server 基类 — 工具注册 + 调用路由 + 重试 + 记忆。

不依赖求职业务，可通过注册工具表扩展。
"""

import asyncio
import json
import sys
import time
import traceback
from typing import Any

from config.settings import settings
from service.mcp_memory import MCPMemory, validate_params
from utils.logger import get_logger

logger = get_logger("mcp")

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class MCPToolServer:
    """
    通用 MCP 工具服务器。

    用法:
        server = MCPToolServer("my-agent")

        @server.register("my_tool", "description", {"param": str})
        async def handle_my_tool(args): return [TextContent(type="text", text="done")]

        await server.run()
    """

    def __init__(self, name: str = "agent"):
        if not MCP_AVAILABLE:
            raise ImportError("MCP SDK not installed: pip install mcp")
        self.name = name
        self.server = Server(name)
        self._tools: list[Tool] = []
        self._handlers: dict[str, callable] = {}
        self.memory = MCPMemory()
        self.max_retries = settings.MCP_MAX_RETRIES

        # Register list_tools / call_tool
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)
        logger.info(f"MCPToolServer init: {name} | tools=0 | retries={self.max_retries}")

    def register(self, name: str, description: str, schema: dict, handler: callable):
        """注册一个 MCP 工具"""
        tool = Tool(name=name, description=description, inputSchema={
            "type": "object", "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        })
        self._tools.append(tool)
        self._handlers[name] = handler
        logger.info(f"Tool registered: {name}")

    def register_batch(self, tools: list[dict]):
        """批量注册工具 [{name, description, schema, handler}, ...]"""
        for t in tools:
            self.register(t["name"], t["description"], t.get("schema", {}), t["handler"])

    async def _list_tools(self):
        return self._tools

    async def _call_tool(self, name: str, arguments: dict):
        handler = self._handlers.get(name)
        if not handler:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        start_time = time.time()

        # ---- Param pre-validation (v3.1) ----
        valid, msg = validate_params(name, arguments)
        if not valid:
            logger.warning(f"Tool {name} param validation failed: {msg}")
            return [TextContent(type="text", text=f"参数校验失败: {msg}")]

        # ---- Memory cache ----
        cached = self.memory.get(name, arguments)
        if cached is not None:
            self.memory.log_call(name, arguments, str(cached), 0, 0, "", call_id=f"{name}_cached")
            logger.debug(f"Tool {name} CACHE HIT")
            return [TextContent(type="text", text=str(cached))]

        # ---- Execute with retry + detailed logging ----
        last_error = ""
        for attempt in range(self.max_retries):
            try:
                result = await handler(arguments) if asyncio.iscoroutinefunction(handler) else handler(arguments)
                duration = (time.time() - start_time) * 1000
                self.memory.put(name, arguments, result)
                self.memory.log_call(name, arguments, str(result), duration, attempt,
                                     call_id=f"{name}_{int(start_time)}")
                retry_info = f" (retry={attempt})" if attempt > 0 else ""
                logger.info(f"Tool '{name}' OK{retry_info} | {duration:.0f}ms | params: {json.dumps(arguments, ensure_ascii=False)[:80]}")
                return result
            except Exception as e:
                last_error = str(e)
                wait = 2 ** attempt
                logger.warning(f"Tool '{name}' FAIL attempt={attempt+1}/{self.max_retries} | {last_error[:100]} | next_retry={wait}s")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait)

        duration = (time.time() - start_time) * 1000
        self.memory.log_call(name, arguments, None, duration, self.max_retries, error=last_error,
                             call_id=f"{name}_{int(start_time)}")
        logger.error(f"Tool '{name}' EXHAUSTED retries | duration={duration:.0f}ms | error={last_error[:200]}")
        return [TextContent(type="text", text=f"工具 '{name}' 执行失败（已重试{self.max_retries}次）: {last_error}")]

    async def run(self):
        """启动 stdio MCP Server"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream,
                                  self.server.create_initialization_options())
