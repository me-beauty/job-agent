#!/usr/bin/env python3
"""
训练器 — 模型训练 + 早停 + 版本管理 + 评估报告。

完全通用，不依赖求职业务。
"""

import datetime
import json
import os
from pathlib import Path

import numpy as np
try:
    import torch
    import torch.nn as nn
    _TORCH_OK = True
except ImportError:
    class _DummyModule:
        def __init__(self, *a, **kw): pass
        def __call__(self, *a, **kw): return self
        def __getattr__(self, name): return _DummyModule()
    class _DummyNN:
        Module = _DummyModule
        def __getattr__(self, name): return _DummyModule()
    torch = _DummyModule()
    nn = _DummyNN()
    _TORCH_OK = False

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("model.trainer")

# 模型路径优先用新的 model/ 目录，兼容旧 tf_match_model/
MODEL_DIR = settings.MODEL_DIR
OLD_MODEL_DIR = settings.OLD_MODEL_DIR


class MatchTrainer:
    """
    训练器。

    用法:
        trainer = MatchTrainer(vocab_size=8000)
        result = trainer.fit((X_tr, y_tr), (X_val, y_val), epochs=30, lr=0.001)
        trainer.save("my_model")
    """

    def __init__(self, vocab_size: int = None, embed_dim: int = None, hidden_dim: int = None):
        from model.match_net import MatchModel
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = MatchModel(vocab_size, embed_dim, hidden_dim).to(self.device)
        self.vocab_size = vocab_size or settings.TRAIN_VOCAB_SIZE
        self._history: dict = {}
        self._best_loss = float("inf")
        logger.info(f"Trainer initialized | device={self.device} vocab={self.vocab_size}")

    def fit(self, train_data: tuple, val_data: tuple = None,
            epochs: int = None, lr: float = None, batch_size: int = None,
            use_claude: bool = False) -> dict:
        """
        训练模型。

        Args:
            train_data: (resume_ids, jd_ids, labels)  每个 shape (N, max_len), (N,), (N,)
            val_data:   同上
            epochs:     训练轮次
            lr:         学习率
            batch_size: 批次大小
            use_claude: 是否调用 Claude 分析（L3）

        Returns:
            {"model_name": "...", "epochs": N, "val_mae": ..., "accuracy": ..., "model_path": ...}
        """
        epochs = epochs or settings.TRAIN_EPOCHS
        lr = lr or settings.TRAIN_LR
        batch_size = batch_size or settings.TRAIN_BATCH_SIZE
        patience = settings.TRAIN_EARLY_STOP

        tr_r, tr_j, tr_y = train_data
        has_val = val_data is not None
        if has_val:
            vl_r, vl_j, vl_y = val_data

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        loss_fn = nn.MSELoss()
        history = {"loss": [], "val_loss": [], "mae": [], "val_mae": []}
        best_val = float("inf")
        patience_counter = 0
        model_name = self._next_version()

        print(f"\n{'='*50}\n  Training {model_name} | epochs={epochs} lr={lr} batch={batch_size}\n{'='*50}\n")

        for epoch in range(epochs):
            self.model.train()
            total_loss = 0.0; total_mae = 0.0; n_batches = 0
            perm = torch.randperm(len(tr_y))

            for i in range(0, len(tr_y), batch_size):
                idx = perm[i:i+batch_size]
                r_b = tr_r[idx].to(self.device); j_b = tr_j[idx].to(self.device)
                y_b = tr_y[idx].to(self.device) / 100.0

                optimizer.zero_grad()
                pred = self.model(r_b, j_b)
                loss = loss_fn(pred, y_b)
                loss.backward(); optimizer.step()
                total_loss += loss.item()
                total_mae += (pred - y_b).abs().mean().item() * 100
                n_batches += 1

            avg_loss = total_loss / max(n_batches, 1)
            avg_mae  = total_mae / max(n_batches, 1)

            # Validation
            val_loss = val_mae = 0.0
            if has_val:
                self.model.eval()
                with torch.no_grad():
                    vp = self.model(vl_r.to(self.device), vl_j.to(self.device))
                    val_loss = loss_fn(vp, vl_y.to(self.device) / 100.0).item()
                    val_mae  = (vp - vl_y.to(self.device) / 100.0).abs().mean().item() * 100

            history["loss"].append(round(avg_loss, 4)); history["val_loss"].append(round(val_loss, 4))
            history["mae"].append(round(avg_mae, 2));   history["val_mae"].append(round(val_mae, 2))

            # Early stopping
            monitor = val_loss if has_val else avg_loss
            if monitor < best_val:
                best_val = monitor; patience_counter = 0
                self._best_path = MODEL_DIR / f"{model_name}.pt"
                torch.save(self._state_dict(history), self._best_path)
            else:
                patience_counter += 1

            if (epoch + 1) % 5 == 0 or epoch == 0:
                print(f"  Epoch {epoch+1:3d}: loss={avg_loss:.4f} mae={avg_mae:.1f}"
                      f" | v_loss={val_loss:.4f} v_mae={val_mae:.1f} [{patience_counter}/{patience}]")

            if patience_counter >= patience:
                print(f"  Early stop at epoch {epoch+1}")
                break

        self._history = history
        final_path = MODEL_DIR / f"{model_name}_final.pt"
        torch.save(self._state_dict(history), final_path)

        e = len(history["loss"])
        result = {
            "model_name": model_name, "model_path": str(final_path), "epochs": e,
            "loss": history["loss"][-1], "val_loss": history["val_loss"][-1],
            "mae": history["mae"][-1], "val_mae": history["val_mae"][-1],
            "accuracy": round(max(0, 1.0 - history["val_mae"][-1] / 100), 4),
            "n_train": len(tr_y), "n_val": len(vl_y) if has_val else 0,
        }

        # Save eval report
        report_path = MODEL_DIR / f"eval_{model_name}.json"
        report_path.write_text(json.dumps({"history": history, "metrics": result}, indent=2, ensure_ascii=False), encoding="utf-8")
        result["eval_report"] = str(report_path)

        # Also save to old dir for backward compat
        for f in [MODEL_DIR / f"{model_name}.pt", MODEL_DIR / f"{model_name}_final.pt",
                  MODEL_DIR / f"eval_{model_name}.json"]:
            if f.exists():
                try:
                    import shutil
                    shutil.copy2(str(f), str(OLD_MODEL_DIR / f.name))
                except Exception:
                    pass

        # L3: Claude analysis
        if use_claude:
            result["claude_analysis"] = _claude_analysis(result)

        print(f"\n  Done! val_mae={result['val_mae']} acc={result['accuracy']}\n  Model: {final_path}")
        return result

    def load_best(self):
        """加载最优权重"""
        if self._best_path and self._best_path.exists():
            ckpt = torch.load(self._best_path, map_location=self.device, weights_only=False)
            self.model.load_state_dict(ckpt["state_dict"])
            logger.info(f"Loaded best model: {self._best_path.name}")

    def load(self, path: str):
        ckpt = torch.load(path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(ckpt["state_dict"])
        logger.info(f"Loaded model: {path}")

    def _state_dict(self, history: dict) -> dict:
        return {"state_dict": self.model.state_dict(), "vocab_size": self.vocab_size,
                "max_len": settings.TRAIN_MAX_LEN, "history": history,
                "embed_dim": self.model.tower_a.embedding.weight.shape[1],
                "hidden_dim": self.model.tower_a.lstm.hidden_size}

    def _next_version(self) -> str:
        existing = list(MODEL_DIR.glob("job_match_v*.pt")) + \
                    list(OLD_MODEL_DIR.glob("job_match_v*.pt"))
        nums = []
        for p in existing:
            try:
                nums.append(int(p.stem.split("v")[-1].replace("_final", "")))
            except ValueError:
                pass
        v = max(nums) + 1 if nums else 1
        return f"job_match_v{v:03d}"


def _claude_analysis(metrics: dict) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return f"[Rule] val_mae={metrics['val_mae']:.1f}"
    prompt = f"""ML分析。PyTorch BiLSTM匹配模型:
- 验证 MAE: {metrics['val_mae']}
- 准确率: {metrics['accuracy']:.1%}
- 样本: {metrics['n_train']} train / {metrics['n_val']} val
用中文给3条调参建议，不超200字。"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.anthropic.com/v1")
        resp = client.chat.completions.create(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return f"[Rule] val_mae={metrics['val_mae']:.1f}"
