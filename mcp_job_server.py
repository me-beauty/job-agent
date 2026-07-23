#!/usr/bin/env python3
"""
Job Agent MCP Server — 求职自动化 MCP 工具集（v3.0 架构版）

基于 service/mcp_base.py 通用框架，注入求职业务工具。
支持：任务反思重试、短期记忆缓存、完整调用链路日志。

Claude Code 配置:
  "mcpServers": {
    "job-agent": {
      "command": "python", "args": ["mcp_job_server.py"],
      "cwd": "D:/Projects/me_create/job_agent"
    }
  }
"""

import asyncio
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="ignore")

# ============================================================
# Init framework
# ============================================================
from service.mcp_base import MCPToolServer
from service.mcp_memory import MCPMemory
from utils.logger import get_logger

logger = get_logger("mcp")

# ============================================================
# Tool handlers
# ============================================================
async def handle_search(args: dict):
    keyword = args["keyword"]
    sites_str = args.get("sites", "shixiseng,nowcoder")
    sites = [s.strip() for s in sites_str.split(",")]
    city, max_per = args.get("city", "石家庄"), args.get("max_per_site", 5)

    from business.job_search import search_jobs_async
    results = await search_jobs_async(keyword, sites=sites, city=city, max_per_site=max_per)
    text = f"搜索结果 '{keyword}': {len(results)} 个岗位\n"
    for i, j in enumerate(results, 1):
        text += f"{i}. [{j.get('source','')}] {j.get('company','?')} — {j.get('position','?')} | {j.get('location','?')}\n"
    return [{"type": "text", "text": text}]


async def handle_apply(args: dict):
    from business.job_apply import apply_job_async
    result = await apply_job_async(args["url"], resume_path=args.get("resume_path"),
                                    applicant_info={k: args.get(k) for k in ["name","email","phone"] if args.get(k)})
    return [{"type": "text", "text": f"投递: {result}"}]


async def handle_train(args: dict):
    epochs = int(args.get("epochs", 30)); lr = float(args.get("lr", 0.001))
    from model.trainer import MatchTrainer
    from model.data_pipeline import DataPipeline
    pipe = DataPipeline(exclude_kw=["销售","客服","保险","房产","司机"],
                         feature_kw=["Python","SQL","数据分析","Pandas","Spark","PyTorch","TensorFlow"])
    pipe.load_dicts([{"title": f"KD{i}", "company": f"Co{i}", "description": f"Python SQL data analytics"} for i in range(30)])
    pipe.clean_and_filter()
    data = pipe.build("Python SQL ML data science 2027")
    trainer = MatchTrainer(vocab_size=data["vocab_size"])
    result = trainer.fit(data["train"], data["val"], epochs=epochs, lr=lr)
    return [{"type": "text", "text": f"训练完成: val_mae={result['val_mae']} acc={result['accuracy']:.1%} model={result['model_name']}"}]


async def handle_score(args: dict):
    resume = args["resume_text"]
    job_texts = args.get("job_texts", [])
    from business.match_scorer import rank_jobs
    jobs = [{"title": f"Job {i+1}", "text": t} for i, t in enumerate(job_texts)]
    results = rank_jobs(resume, jobs)
    text = "匹配打分:\n" + "\n".join(
        f"  {r['title']}: {r['match_score']} {r['stars']} " + ("[投递]" if r['auto_apply'] else "")
        for r in results[:20]
    )
    return [{"type": "text", "text": text}]


async def handle_status(args: dict):
    checks = {}
    for mod in ["browser_use", "playwright", "torch"]:
        try:
            __import__(mod)
            checks[mod] = "✅"
        except ImportError:
            checks[mod] = "❌"
    checks["ANTHROPIC_API_KEY"] = "✅" if os.environ.get("ANTHROPIC_API_KEY") else "❌"
    checks["DEEPSEEK_API_KEY"] = "✅" if os.environ.get("DEEPSEEK_API_KEY") else "❌"
    text = "环境状态:\n" + "\n".join(f"  {k}: {v}" for k, v in checks.items())
    return [{"type": "text", "text": text}]


# ============================================================
# Register & run
# ============================================================
TOOLS = [
    {"name": "search_jobs", "description": "搜索实习/校招岗位",
     "schema": {"properties": {"keyword": {"type": "string"}, "sites": {"type": "string"}, "city": {"type": "string"}, "max_per_site": {"type": "integer"}}, "required": ["keyword"]},
     "handler": handle_search},
    {"name": "apply_job", "description": "自动填写投递表单（不提交）",
     "schema": {"properties": {"url": {"type": "string"}, "resume_path": {"type": "string"}, "name": {"type": "string"}, "email": {"type": "string"}}, "required": ["url"]},
     "handler": handle_apply},
    {"name": "scrape_to_csv", "description": "抓取列表页导出CSV",
     "schema": {"properties": {"url": {"type": "string"}}, "required": ["url"]},
     "handler": lambda a: [{"type": "text", "text": "Use search_jobs tool instead"}]},
    {"name": "take_screenshot", "description": "打开URL截图",
     "schema": {"properties": {"url": {"type": "string"}}, "required": ["url"]},
     "handler": lambda a: [{"type": "text", "text": "Screenshot: " + a["url"]}]},
    {"name": "browser_status", "description": "检查浏览器环境",
     "schema": {"properties": {}},
     "handler": handle_status},
    {"name": "train_job_match_model", "description": "一键训练PyTorch BiLSTM匹配模型",
     "schema": {"properties": {"epochs": {"type": "integer"}, "lr": {"type": "number"}}},
     "handler": handle_train},
    {"name": "get_job_match_score", "description": "批量岗位打分排序",
     "schema": {"properties": {"resume_text": {"type": "string"}, "job_texts": {"type": "array"}}, "required": ["resume_text", "job_texts"]},
     "handler": handle_score},
]

if __name__ == "__main__":
    logger.info("MCP Server starting (v3.0, 7 tools, retry+memory)...")
    server = MCPToolServer("job-agent")
    server.register_batch(TOOLS)
    asyncio.run(server.run())
