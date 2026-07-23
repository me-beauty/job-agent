#!/usr/bin/env python3
"""
训练模块 — PyTorch 双塔 BiLSTM 文本匹配回归模型

模型架构：
  resume ─→ Embedding ─→ BiLSTM(128) ─→ MeanPool ─→ Dense(128) ─┐
  jd ─────→ Embedding ─→ BiLSTM(128) ─→ MeanPool ─→ Dense(128) ─┤
                                                                   ├→ Concat → Dense* → score(0-100)

Claude+DeepSeek 分层：
  L2: PyTorch 本地训练
  L3: Claude 分析训练指标 + 调参建议

用法:
  python train.py --data_dir . --epochs 30 --lr 0.001
  python train.py --data_dir . --use_claude
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
MODEL_DIR = Path(__file__).parent / "model_storage"


# ============================================================
# PyTorch 模型定义
# ============================================================

class MatchModel:
    """轻量双塔 BiLSTM 匹配模型"""

    def __init__(self, vocab_size: int, embed_dim: int = 128, hidden_dim: int = 128, max_len: int = 512):
        import torch
        import torch.nn as nn

        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(embed_dim, hidden_dim, batch_first=True, bidirectional=True)
        self.linear = nn.Sequential(
            nn.Linear(hidden_dim * 2, 128),
            nn.ReLU(),
            nn.Dropout(0.2),
        )
        # Fusion
        self.fusion = nn.Sequential(
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )

    def encode(self, x, device):
        import torch
        mask = (x > 0).float().to(device)  # (B, L)
        lens = mask.sum(dim=1).long().clamp(min=1)
        emb = self.embedding(x)  # (B, L, E)
        # Run LSTM without packing (simpler, avoids length mismatch)
        lstm_out, _ = self.lstm(emb)  # (B, L, 2H)
        # Mean pooling over valid tokens
        pooled = (lstm_out * mask.unsqueeze(-1)).sum(dim=1) / lens.unsqueeze(-1).float().to(device)
        return self.linear(pooled)

    def forward(self, resume_ids, jd_ids, device):
        import torch
        r_vec = self.encode(resume_ids, device)
        j_vec = self.encode(jd_ids, device)
        merged = torch.cat([r_vec, j_vec], dim=-1)
        return self.fusion(merged).squeeze(-1)

    def parameters(self):
        for mod in [self.embedding, self.lstm, self.linear, self.fusion]:
            for p in mod.parameters():
                yield p

    def to(self, device):
        import torch.nn as nn
        for mod in [self.embedding, self.lstm, self.linear, self.fusion]:
            mod.to(device)

    def train(self):
        import torch.nn as nn
        for mod in [self.embedding, self.lstm, self.linear, self.fusion]:
            mod.train()

    def eval(self):
        import torch.nn as nn
        for mod in [self.embedding, self.lstm, self.linear, self.fusion]:
            mod.eval()

    def state_dict(self) -> dict:
        return {
            "embedding": self.embedding.state_dict(),
            "lstm": self.lstm.state_dict(),
            "linear": self.linear.state_dict(),
            "fusion": self.fusion.state_dict(),
        }

    def load_state_dict(self, sd: dict):
        self.embedding.load_state_dict(sd["embedding"])
        self.lstm.load_state_dict(sd["lstm"])
        self.linear.load_state_dict(sd["linear"])
        self.fusion.load_state_dict(sd["fusion"])


# ============================================================
# 训练
# ============================================================

def train_model(
    data: dict = None,
    vocab_size: int = None,
    max_len: int = 512,
    epochs: int = 30,
    lr: float = 1e-3,
    batch_size: int = 16,
    use_claude: bool = False,
    model_name: str = None,
) -> dict:
    import torch
    import torch.nn as nn

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"   Device: {device}")

    # Auto-build data if not provided
    if data is None:
        from .data_pipeline import JobDataPipeline
        pipeline = JobDataPipeline()
        for f in ROOT.glob("*.csv"):
            pipeline.load_csv(str(f))
        for f in sorted(ROOT.glob("daily_report_*.md"))[:3]:
            pipeline.load_markdown(str(f))
        pipeline.load_jobhunt_config()
        pipeline.clean_and_filter()
        tmpl = pipeline.load_resume_template()
        edu = tmpl.get("education", {})
        skills = ", ".join(tmpl.get("skills", []))
        resume = f"{edu.get('major','DS')} {edu.get('school','')} Skills: {skills}"
        data = pipeline.build_dataset(resume)
        vocab_size = data["vocab_size"]
        max_len = data["max_len"]

    (tr_r, tr_j, tr_y) = data["train"]
    (vl_r, vl_j, vl_y) = data["val"]

    print(f"\n{'='*50}")
    print(f"  Training BiLSTM Match Model (PyTorch)")
    print(f"  Train: {len(tr_y)}  Val: {len(vl_y)}  Vocab: {vocab_size}")
    print(f"  Epochs: {epochs}  LR: {lr}  Batch: {batch_size}")
    print(f"{'='*50}\n")

    model = MatchModel(vocab_size, max_len=max_len)
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    # ---- Version management ----
    version = _get_next_version()
    model_name = model_name or f"job_match_v{version:03d}"

    # ---- Early stopping ----
    best_val_loss = float("inf")
    early_stop_counter = 0
    early_stop_patience = 8
    history = {"loss": [], "val_loss": [], "mae": [], "val_mae": []}

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0; total_mae = 0.0; n_batches = 0

        perm = torch.randperm(len(tr_y))
        for i in range(0, len(tr_y), batch_size):
            idx = perm[i:i + batch_size]
            r_batch = tr_r[idx].to(device); j_batch = tr_j[idx].to(device)
            y_batch = tr_y[idx].to(device) / 100.0

            optimizer.zero_grad()
            pred = model.forward(r_batch, j_batch, device)
            loss = loss_fn(pred, y_batch)
            loss.backward(); optimizer.step()

            total_loss += loss.item()
            total_mae += (pred - y_batch).abs().mean().item() * 100
            n_batches += 1

        avg_loss = total_loss / max(n_batches, 1)
        avg_mae = total_mae / max(n_batches, 1)

        model.eval()
        with torch.no_grad():
            val_pred = model.forward(vl_r.to(device), vl_j.to(device), device)
            val_loss = loss_fn(val_pred, vl_y.to(device) / 100.0).item()
            val_mae = (val_pred - vl_y.to(device) / 100.0).abs().mean().item() * 100

        history["loss"].append(round(avg_loss, 4)); history["val_loss"].append(round(val_loss, 4))
        history["mae"].append(round(avg_mae, 2)); history["val_mae"].append(round(val_mae, 2))

        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss; early_stop_counter = 0
            save_path = MODEL_DIR / f"{model_name}.pt"
            torch.save({"state_dict": model.state_dict(), "vocab_size": vocab_size,
                        "max_len": max_len, "history": history}, save_path)
        else:
            early_stop_counter += 1

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1:3d}: loss={avg_loss:.4f} mae={avg_mae:.1f} | val_loss={val_loss:.4f} val_mae={val_mae:.1f} [{early_stop_counter}/{early_stop_patience}]")

        if early_stop_counter >= early_stop_patience:
            print(f"  Early stopping at epoch {epoch+1}")
            break

    final_path = MODEL_DIR / f"{model_name}.pt"
    torch.save({"state_dict": model.state_dict(), "vocab_size": vocab_size,
                "max_len": max_len, "history": history}, final_path)

    e = len(history["loss"])
    result = {
        "model_path": str(final_path), "model_name": model_name, "epochs": e,
        "loss": history["loss"][-1], "val_loss": history["val_loss"][-1],
        "mae": history["mae"][-1], "val_mae": history["val_mae"][-1],
        "accuracy": round(max(0, 1.0 - history["val_mae"][-1] / 100), 4),
        "n_train": len(tr_y), "n_val": len(vl_y),
    }

    # ---- Save eval report ----
    report_path = MODEL_DIR / f"eval_report_{model_name}.json"
    report_path.write_text(json.dumps({"history": history, "metrics": result}, indent=2, ensure_ascii=False), encoding="utf-8")
    result["eval_report"] = str(report_path)
    print(f"  Eval report: {report_path}")

    # L3: Claude analysis
    if use_claude:
        analysis = _call_claude_analysis(result)
        result["claude_analysis"] = analysis
        print(f"\n  Claude: {analysis}")

    print(f"\n  Done! val_mae={result['val_mae']} acc={result['accuracy']}")
    print(f"  Model: {final_path}")
    return result


def _get_next_version():
    """Auto-increment version number from model_storage files"""
    existing = list(MODEL_DIR.glob("job_match_v*.pt"))
    if not existing:
        return 1
    nums = []
    for p in existing:
        try:
            nums.append(int(p.stem.split("v")[-1]))
        except ValueError:
            pass
    return max(nums) + 1 if nums else 1


def _call_claude_analysis(metrics: dict) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    val_mae = metrics['val_mae']
    prompt = f"""ML训练分析。PyTorch BiLSTM人岗匹配模型结果:
- 训练 epochs: {metrics['epochs']}
- 验证 MAE: {val_mae}
- 验证 accuracy: {metrics['accuracy']:.1%}
- 样本: {metrics['n_train']} train / {metrics['n_val']} val
用中文给3条调参建议，不超200字。"""
    if not api_key:
        return f"[Rule] MAE={val_mae}. " + ("OK" if val_mae < 15 else "Need more data or tune LR")
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
        return f"[Rule] MAE={val_mae}."


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="PyTorch job match training")
    parser.add_argument("--data_dir", default=str(ROOT))
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--use_claude", action="store_true")
    parser.add_argument("--name", help="Model name")
    args = parser.parse_args()
    os.chdir(args.data_dir)

    from .data_pipeline import JobDataPipeline
    pipeline = JobDataPipeline()
    for f in ROOT.glob("*.csv"):
        pipeline.load_csv(str(f))
    for f in sorted(ROOT.glob("daily_report_*.md"))[:3]:
        pipeline.load_markdown(str(f))
    pipeline.load_jobhunt_config()
    pipeline.clean_and_filter()
    tmpl = pipeline.load_resume_template()
    edu = tmpl.get("education", {})
    skills = ", ".join(tmpl.get("skills", []))
    resume = f"{edu.get('major', 'DS')} {edu.get('school', '')} Skills: {skills}"
    data = pipeline.build_dataset(resume)

    result = train_model(
        data=data,
        vocab_size=data["vocab_size"],
        max_len=data["max_len"],
        epochs=args.epochs,
        lr=args.lr,
        batch_size=args.batch_size,
        use_claude=args.use_claude,
        model_name=args.name,
    )
    print(f"\n  Result: {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
