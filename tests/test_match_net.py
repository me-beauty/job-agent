#!/usr/bin/env python3
"""单元测试：BiLSTM 匹配模型"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch
from model.match_net import MatchModel, BiLSTMTextTower
from model.inference import text_to_ids, _pad_tensor


def test_tower_output_shape():
    """TextTower 输出形状正确"""
    tower = BiLSTMTextTower(vocab_size=4000, embed_dim=64, hidden_dim=64)
    x = torch.randint(1, 100, (4, 100))  # (batch=4, len=100)
    out = tower(x)
    assert out.shape == (4, 64), f"Expected (4, 64), got {out.shape}"


def test_model_forward():
    """MatchModel 前向输出形状正确"""
    model = MatchModel(vocab_size=4000, embed_dim=64, hidden_dim=64)
    a = torch.randint(1, 100, (4, 100))
    b = torch.randint(1, 100, (4, 100))
    scores = model(a, b)
    assert scores.shape == (4,), f"Expected (4,), got {scores.shape}"
    assert (0 <= scores).all() and (scores <= 1).all(), "Scores should be in [0,1]"


def test_embedding_export():
    """Embedding 导出形状正确"""
    model = MatchModel(vocab_size=4000, embed_dim=64, hidden_dim=64)
    x = torch.randint(1, 100, (3, 100))
    vecs = model.export_embedding(x)
    assert vecs.shape == (3, 64), f"Expected (3, 64), got {vecs.shape}"


def test_text_to_ids():
    """字符编码函数正常工作"""
    ids = text_to_ids("Python 数据分析", max_len=512)
    assert len(ids) > 0
    assert all(isinstance(i, int) for i in ids)


def test_pad_tensor():
    """填充张量形状正确"""
    ids_list = [text_to_ids("Python"), text_to_ids("SQL 数据分析")]
    t = _pad_tensor(ids_list, max_len=512)
    assert t.shape == (2, 512)
    assert t.dtype == torch.long


if __name__ == "__main__":
    test_tower_output_shape();    print("✅ test_tower_output_shape")
    test_model_forward();         print("✅ test_model_forward")
    test_embedding_export();      print("✅ test_embedding_export")
    test_text_to_ids();           print("✅ test_text_to_ids")
    test_pad_tensor();            print("✅ test_pad_tensor")
    print("\n🎉 All tests passed!")
