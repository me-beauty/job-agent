#!/usr/bin/env python3
"""全局配置管理 — 统一加载环境变量和默认值"""

import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

class Settings:
    """所有可配置项集中管理"""

    # LLM API Keys
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

    # Auth
    JOB_AGENT_TOKEN = os.environ.get("JOB_AGENT_TOKEN", "job-agent-demo-token")
    JOB_AGENT_LLM   = os.environ.get("JOB_AGENT_LLM", "claude")

    # Paths
    DB_PATH      = ROOT / "db" / "job_agent.db"
    LOG_DIR      = ROOT / "logs"
    MODEL_DIR    = ROOT / "model" / "model_storage"
    OLD_MODEL_DIR = ROOT / "tf_match_model" / "model_storage"  # legacy compat
    VOCAB_PATH   = ROOT / "model" / "vocab.txt"
    OLD_VOCAB_PATH = ROOT / "tf_match_model" / "vocab.txt"

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Rate limits (tokens/sec, max tokens)
    RATE_LIMITS = {
        "/api/train_match_model":    (0.017, 1),    # 1/min
        "/api/search":               (0.083, 5),    # 5/min
        "/api/apply":                (0.083, 5),
        "/api/scrape":               (0.083, 5),
        "/api/calculate_match_score": (0.33, 20),
    }

    # Model training defaults
    TRAIN_EPOCHS        = int(os.environ.get("TRAIN_EPOCHS", "30"))
    TRAIN_LR            = float(os.environ.get("TRAIN_LR", "0.001"))
    TRAIN_BATCH_SIZE    = int(os.environ.get("TRAIN_BATCH_SIZE", "16"))
    TRAIN_EARLY_STOP    = int(os.environ.get("TRAIN_EARLY_STOP", "8"))
    TRAIN_EMBED_DIM     = 128
    TRAIN_HIDDEN_DIM    = 128
    TRAIN_MAX_LEN       = 512
    TRAIN_VOCAB_SIZE    = 8000

    # Browser
    BROWSER_HEADLESS       = os.environ.get("BROWSER_HEADLESS", "0") == "1"
    BROWSER_ANTI_DETECT   = os.environ.get("BROWSER_ANTI_DETECT", "1") == "1"
    BROWSER_MAX_PER_CHUNK = int(os.environ.get("BROWSER_MAX_PER_CHUNK", "5"))

    # MCP
    MCP_MEMORY_TTL      = int(os.environ.get("MCP_MEMORY_TTL", "300"))
    MCP_MAX_RETRIES      = int(os.environ.get("MCP_MAX_RETRIES", "3"))
    MCP_CALL_LOG         = ROOT / "logs" / "mcp_calls.jsonl"

    # Email
    QQ_EMAIL     = os.environ.get("QQ_EMAIL", "")
    QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE", "")

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.LOG_DIR, cls.MODEL_DIR, cls.OLD_MODEL_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def to_dict(cls) -> dict:
        return {k: str(v) if isinstance(v, Path) else v
                for k, v in vars(cls).items()
                if k.isupper() and not k.startswith("_")}


settings = Settings()
settings.ensure_dirs()
