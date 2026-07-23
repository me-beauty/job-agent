#!/usr/bin/env python3
"""
双塔 BiLSTM 文本匹配模型 — 纯 PyTorch nn.Module，零业务依赖。

架构:
  text_a → Embedding → BiLSTM → MeanPool → Dense ─┐
  text_b → Embedding → BiLSTM → MeanPool → Dense ─┤
                                                    ├→ Concat → Dense* → sigmoid → score
"""

try:
    import torch
    import torch.nn as nn
    _TORCH_OK = True
except ImportError:
    # Dummy fallback so class definitions don't crash
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


class BiLSTMTextTower(nn.Module):
    """单塔文本编码器"""

    def __init__(self, vocab_size: int, embed_dim: int = 128, hidden_dim: int = 128):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(embed_dim, hidden_dim, batch_first=True, bidirectional=True)
        self.proj = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: (B, L) int ids
        → (B, hidden_dim) text vector
        """
        mask = (x > 0).float().unsqueeze(-1)        # (B, L, 1)
        lens = mask.squeeze(-1).sum(dim=1).clamp(min=1)  # (B,)
        emb = self.embedding(x)                     # (B, L, E)
        lstm_out, _ = self.lstm(emb)                # (B, L, 2H)
        pooled = (lstm_out * mask).sum(dim=1) / lens.unsqueeze(-1)  # (B, 2H)
        return self.proj(pooled)                    # (B, H)


class MatchModel(nn.Module):
    """
    双塔匹配模型。

    Args:
        vocab_size: 词表大小
        embed_dim:  嵌入维度
        hidden_dim: LSTM 隐层维度（双向后输出 2*hidden_dim）
    """

    def __init__(self, vocab_size: int = None, embed_dim: int = None, hidden_dim: int = None):
        super().__init__()
        vocab_size = vocab_size or settings.TRAIN_VOCAB_SIZE
        embed_dim = embed_dim or settings.TRAIN_EMBED_DIM
        hidden_dim = hidden_dim or settings.TRAIN_HIDDEN_DIM

        self.tower_a = BiLSTMTextTower(vocab_size, embed_dim, hidden_dim)
        self.tower_b = BiLSTMTextTower(vocab_size, embed_dim, hidden_dim)
        self.fusion = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim // 2, 1),
            nn.Sigmoid(),
        )

    def encode_a(self, ids: torch.Tensor) -> torch.Tensor:
        """编码 text_a → 向量（用于 Embedding 导出）"""
        return self.tower_a(ids)

    def encode_b(self, ids: torch.Tensor) -> torch.Tensor:
        """编码 text_b → 向量"""
        return self.tower_b(ids)

    def forward(self, a_ids: torch.Tensor, b_ids: torch.Tensor) -> torch.Tensor:
        """返回 (B,) 匹配分数 [0, 1]"""
        va = self.encode_a(a_ids)
        vb = self.encode_b(b_ids)
        merged = torch.cat([va, vb], dim=-1)
        return self.fusion(merged).squeeze(-1)

    def export_embedding(self, text_ids: torch.Tensor) -> torch.Tensor:
        """导出文本 Embedding 向量 (B, hidden_dim)，用于相似度召回"""
        self.eval()
        with torch.no_grad():
            return self.encode_a(text_ids)
