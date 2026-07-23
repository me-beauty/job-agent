# Job Agent v3.1 — 架构文档 (面试版)

## 一、系统全景数据流

```
                           ┌──────────────────────┐
                           │    用户入口 (4种)     │
                           │  Web / API / MCP /   │
                           │  定时任务 (08:00)     │
                           └─────────┬────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          ▼                          ▼                          ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   web_server.py  │    │ mcp_job_server   │    │ daily_job_search │
│   Flask REST     │    │ MCP over stdio   │    │ (定时任务)        │
│   24 API 端点     │    │ 7 工具 + 重试    │    │ 精准/快速双模式   │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                     business/ (求职业务插件)                       │
│  web_api.py  job_search.py  job_apply.py  match_scorer.py        │
│  ── 12 Flask Blueprint + HTTP鉴权 + 限流 + 异步任务 ──           │
└──────┬──────────────────────────────────────────────────┬────────┘
       │                                                  │
       ▼                                                  ▼
┌─────────────┐  ┌─────────────┐  ┌──────────────────────────────┐
│   engine/   │  │   model/    │  │         service/             │
│ 通用智能引擎 │  │ PyTorch模型 │  │        MCP 服务层            │
├─────────────┤  ├─────────────┤  ├──────────────────────────────┤
│ llm_factory │  │ match_net   │  │ mcp_base (重试+校验+路由)     │
│ browser_ctrl│  │ trainer     │  │ mcp_memory (缓存+DB日志+规划) │
│ task_mgr    │  │ inference   │  │                              │
│ priority_q  │  │ evaluation  │  │ TaskPlanner (指令→工具序列)   │
│             │  │ data_pipe   │  │ validate_params (前置校验)    │
│             │  │ vector_store│  │                              │
│             │  │ monitor     │  │                              │
│             │  │ sync_data   │  │                              │
└──────┬──────┘  └──────┬──────┘  └──────────────┬───────────────┘
       │                │                        │
       └────────────────┼────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                    基础设施 (Infrastructure)                       │
├──────────────────────────────────────────────────────────────────┤
│  db/            utils/           config/         logs/           │
│  SQLite 5表     logger           settings.py     daily rotation  │
│  jobs/tasks/    rate_limiter     env vars 管理                   │
│  apply_logs/    browser_anti                                     │
│  models/        (随机UA/延迟/                                     │
│  tool_calls     captcha检测)                                     │
│  sample_stats                                                   │
└──────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                        外部依赖                                   │
│  Claude API    DeepSeek API    ChromaDB     Chromium+Playwright  │
│  (搜索+分析)   (文本预处理)     (向量召回)    (浏览器自动化)        │
└──────────────────────────────────────────────────────────────────┘
```

## 二、核心链路详解

### 链路 A: 岗位搜索 → 日报生成 → 邮件推送

```
用户触发 (Web/API/定时)
  → business/job_search (browser-use 打开招聘网站)
  → engine/llm_factory (Claude/DeepSeek 选择)
  → engine/browser_controller (Chromium 操控)
  → 清洗去重 (report_utils)
  → 日报 Markdown 保存
  → send_email.py (QQ SMTP 卡片式 HTML)
```

### 链路 B: 语义匹配全链路 (两阶段)

```
用户简历文本
  │
  ├── Stage 1: 向量粗召回 (ChromaDB)
  │   model/inference.embed() → 128维向量
  │   → ChromaDB cosine 召回 top-K (毫秒级)
  │
  └── Stage 2: BiLSTM 精排 (PyTorch)
      model/match_net 双塔
      → 0-100 匹配分数 + ⭐ 评级 + S/A/B/C/D 等级
      → ≥70 分标记 auto_apply
```

### 链路 C: MCP 工具调用 (Claude Code → Agent)

```
Claude Code 自然语言指令
  → service/mcp_base.MCPToolServer._call_tool()
      ├── validate_params() 参数前置校验
      ├── MCPMemory.get() 缓存命中 ? 直接返回
      ├── handler() 执行 (最多 3 次重试, 指数退避)
      ├── MCPMemory.put() 写入缓存 (TTL 5min)
      └── MCPMemory.log_call() 双写 (JSONL + SQLite)
  → TextContent 返回 Claude Code
```

### 链路 D: 任务调度 (优先级队列)

```
POST /api/search → TaskManager.create()
  → PriorityTaskQueue.enqueue(task_id, PRIORITY_MEDIUM, fn)
  → 后台 Worker:
      HIGH (训练/打分)      并发=1
      MEDIUM (搜索/投递)     并发=3
      LOW (爬虫/导出)        并发=2
  → TaskManager.update() → DB tasks 表
```

### 链路 E: 数据采集 → 训练 → 监控

```
model/sync_data.full_sync()
  → CSV + MD + jobhunt → DB jobs 表
  → DB → ChromaDB vector_store
  → model/monitor.take_snapshot() → DB sample_stats 表
  → model/data_pipeline → DataPipeline.build()
  → model/trainer.fit() → BiLSTM 训练
      ├── 早停 (patience=8)
      ├── 版本管理 (v001.pt / v002.pt ...)
      ├── 评估报告 (eval_*.json)
      └── 后向兼容 (旧 .pt 自动迁移)
```

## 三、分层调度规则 (LLM Cost)

| Layer | Model | Task | When | Cost |
|-------|-------|------|------|------|
| L1 | **DeepSeek** | JD denoise + keyword + augmentation | Data pipeline | Low |
| L2 | **PyTorch (CPU)** | BiLSTM train + inference | Every query | **$0** |
| L3 | **Claude** | Training metric analysis | Post-train only | ~1/session |
| L4 | **PyTorch (CPU)** | Match scoring + embedding | Every query | **$0** |
| L5 | **ChromaDB** | Vector recall (cosine) | Every query | **$0** |

## 四、数据库表设计

| Table | Rows | Purpose |
|-------|------|---------|
| `jobs` | ~200 | 岗位数据 (去重+过滤) |
| `tasks` | ~50 | 异步任务生命周期 |
| `apply_logs` | ~20 | 投递操作记录 |
| `models` | ~5 | 模型版本管理 |
| `tool_calls` | ~200 | MCP 工具调用日志 |
| `sample_stats` | ~50 | 训练样本分布快照 |

## 五、API 端点清单 (24 个)

### 通用 (3)
`GET /` `GET /login` `GET /logout`

### 报告 (2)
`GET /report/<path>` `GET /files/<path>`

### 浏览器自动化 (6)
`GET /api/status` `GET /api/sites` `POST /api/search` `POST /api/apply`
`POST /api/scrape` `GET /api/browser-check`

### 匹配模型 (4)
`POST /api/train_match_model` `POST /api/calculate_match_score`
`GET /api/models` `POST /api/models/switch`

### 向量检索 (4)
`GET /api/vector/stats` `POST /api/vector/recall`
`POST /api/vector/semantic` `POST /api/vector/sync`

### 队列 & 监控 (5)
`GET /api/queue/stats` `POST /api/search-prioritized`
`GET /api/tasks` `GET /api/task/<id>`
`GET /api/tool-calls` `GET /api/data/stats`
`POST /api/data/sync` `POST /api/data/snapshot`

## 六、MCP 工具清单 (7)

| 工具 | 参数 | 说明 |
|------|------|------|
| `search_jobs` | keyword, sites, city | 多站并发搜索 |
| `apply_job` | url, resume_path, name, email | 自动填表 (不提交) |
| `scrape_to_csv` | url | 列表导出 |
| `take_screenshot` | url | 页面截图 |
| `browser_status` | — | 环境检查 |
| `train_job_match_model` | epochs, lr | 一键训练 |
| `get_job_match_score` | resume_text, job_texts | 批量打分排序 |

## 七、部署启动

```bash
# 1. Install
pip install -r requirements.txt
playwright install chromium

# 2. Start
start_all.bat
# Or: python web_server.py           # Flask :5000
#     ngrok http 5000                # public URL

# 3. Verify
curl http://127.0.0.1:5000/api/status -H "Authorization: Bearer job-agent-demo-token"
python -c "import tests.test_match_net; import tests.test_evaluation; print('OK')"
```
