# 🤖 Job Agent — AI-powered job search & auto-apply system

```
┌──────────────────────────────────────────────────────────────────┐
│                        Data Sources (4)                          │
│  WebSearch ◇ jobhunt-cli (8 BigTech) ◇ browser-use ◇ history    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐  ┌───────────┐  ┌──────────────┐
   │ Claude  │  │ DeepSeek  │  │ PyTorch      │
   │ Code    │  │ JD denoise│  │ BiLSTM match │
   │ search  │  │ keywords  │  │ model (local) │
   └────┬────┘  └─────┬─────┘  └──────┬───────┘
        │             │              │
        └──────┬──────┘              │
               ▼                     ▼
   ┌──────────────────┐   ┌──────────────────┐
   │ Daily Reports    │   │ Match Scoring    │
   │ (Precise/Quick)  │   │ (0-100 + stars)  │
   └────────┬─────────┘   └────────┬─────────┘
            │                      │
            ▼                      ▼
   ┌──────────────────────────────────────────┐
   │            Flask Web Dashboard            │
   │  /  Dashboard  /api/*  REST + MCP        │
   │  Browser panel  Model panel  Task panel  │
   └──────────────────────────────────────────┘
            │
   ┌────────┴────────┐
   ▼                 ▼
 Email (QQ SMTP)   ngrok (public URL)
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key |
| `JOB_AGENT_TOKEN` | `job-agent-demo-token` | API auth token |
| `JOB_AGENT_LLM` | `claude` | Default LLM provider |
| `LOG_LEVEL` | `INFO` | Logging level |
| `QQ_EMAIL` | — | QQ email for SMTP |
| `QQ_AUTH_CODE` | — | QQ email auth code |

---

## Quick Start

```bash
# 1. Install deps
pip install -r requirements_browser.txt
playwright install chromium

# 2. Start
start_all.bat

# Or manually:
python web_server.py          # Flask :5000
ngrok http 5000               # public tunnel
```

---

## API Reference

All `/api/*` routes require `Authorization: Bearer <token>`.

### Browser Automation
```bash
# Search jobs
curl -X POST http://127.0.0.1:5000/api/search \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"keyword":"data science intern","city":"Beijing"}'

# Apply to job (score filter: skip if < 70)
curl -X POST http://127.0.0.1:5000/api/apply \
  -H "Authorization: Bearer TOKEN" \
  -d '{"url":"https://...","match_score":85}'

# Scrape to CSV
curl -X POST http://127.0.0.1:5000/api/scrape \
  -H "Authorization: Bearer TOKEN" \
  -d '{"url":"https://...","output_name":"jobs_export"}'
```

### Match Model
```bash
# Train model
curl -X POST http://127.0.0.1:5000/api/train_match_model \
  -H "Authorization: Bearer TOKEN" \
  -d '{"epochs":30,"lr":0.001}'

# Score jobs
curl -X POST http://127.0.0.1:5000/api/calculate_match_score \
  -H "Authorization: Bearer TOKEN" \
  -d '{"resume_text":"Python SQL ML...","jobs":[{"title":"DA Intern","description":"..."}]}'
```

### Management
```bash
# Model versions
curl http://127.0.0.1:5000/api/models -H "Authorization: Bearer TOKEN"

# Switch active model
curl -X POST http://127.0.0.1:5000/api/models/switch \
  -H "Authorization: Bearer TOKEN" \
  -d '{"name":"job_match_v003"}'

# Tasks list
curl http://127.0.0.1:5000/api/tasks -H "Authorization: Bearer TOKEN"

# Environment check
curl http://127.0.0.1:5000/api/browser-check -H "Authorization: Bearer TOKEN"
```

---

## MCP Tools (Claude Code)

| Tool | Description |
|------|-------------|
| `search_jobs` | Search jobs across recruitment sites |
| `apply_job` | Auto-fill application forms |
| `scrape_to_csv` | Scrape listings → CSV |
| `take_screenshot` | Screenshot a URL |
| `browser_status` | Check browser environment |
| `train_job_match_model` | Train PyTorch BiLSTM match model |
| `get_job_match_score` | Batch score jobs, return sorted |

---

## Project Structure

```
job_agent/
├── web_server.py              # Flask dashboard + REST API
├── job_browser.py             # browser-use automation core
├── job_browser_web.py         # Flask blueprint (/api/*)
├── mcp_job_server.py          # MCP server (7 tools)
├── daily_job_search.py        # Precise report mode
├── daily_job_search_quick.py  # Quick/auto report mode
├── report_utils.py            # Shared utilities (dedup/diff/jobhunt)
├── send_email.py              # QQ SMTP email sender
├── db/
│   ├── database.py            # SQLite CRUD (jobs/tasks/models/logs)
│   └── schema.sql             # DDL
├── tf_match_model/
│   ├── data_pipeline.py       # Multi-source data → training data
│   ├── train.py               # PyTorch BiLSTM trainer
│   ├── inference.py           # Model loading + inference
│   ├── model_storage/         # .pt weights
│   └── vocab.txt              # Vocabulary cache
├── utils/
│   ├── logger.py              # File + console logging
│   ├── rate_limiter.py        # Token bucket rate limiter
│   └── browser_anti_detect.py # Random UA/delay/window/chunking
├── logs/                      # Runtime logs
├── start_all.bat              # One-click launcher
└── requirements_browser.txt   # Python deps
```

---

## Cost Discipline (LLM Scheduling)

| Layer | Model | Task | When |
|-------|-------|------|------|
| L1 | **DeepSeek** | JD denoising, keyword extraction, data augmentation | Data pipeline |
| L2 | **PyTorch (local)** | BiLSTM training + inference | Training / each query |
| L3 | **Claude** | Training metric analysis, strategy advice | After training only |
| L4 | **PyTorch (local)** | Match scoring | Each query |

**No unnecessary Claude calls.** DeepSeek handles bulk text preprocessing (cheaper). Claude is used only for post-training analysis (~1 call per training session).

---

## License

MIT
