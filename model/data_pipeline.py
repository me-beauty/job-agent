#!/usr/bin/env python3
"""
通用文本数据管线 — 读取 CSV/MD → 清洗 → 特征提取 → 训练集。

业务无关：通过传入 exclude_kw / feature_kw 配置过滤规则。
"""

import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent


def _call_deepseek_preprocess(text: str, task: str = "denoise", api_key: str = "") -> str:
    """DeepSeek 文本预处理（L1）"""
    if not api_key:
        return _rule_preprocess(text, task)
    try:
        from openai import OpenAI
    except ImportError:
        return _rule_preprocess(text, task)
    prompts = {
        "denoise": "去除以下JD中无关内容（HTML、公司介绍、福利），只保留岗位职责和任职要求。纯文本，不超300字。\n\n",
        "keywords": "从以下JD提取10-15个核心技能关键词，逗号分隔，不要解释。\n\n",
    }
    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompts.get(task, "denoise") + text[:2000]}],
            max_tokens=500, temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return _rule_preprocess(text, task)


def _rule_preprocess(text: str, task: str) -> str:
    if task == "keywords":
        # Will be overridden by caller with actual feature_kw
        return text[:200]
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:500]


def _normalize(t):
    return t.strip().lower().replace(" ", "").replace("　", "")


# ---- 主管线类 ----

class DataPipeline:
    """
    通用文本匹配数据管线。

    用法:
        pipe = DataPipeline(exclude_kw=["销售","客服"], feature_kw=["Python","SQL"])
        pipe.load_csv("data.csv")
        pipe.clean_and_filter()
        train_data, val_data = pipe.build(resume_text, val_split=0.2)
    """

    def __init__(self, exclude_kw: list = None, feature_kw: list = None,
                 use_deepseek: bool = False, max_len: int = 512):
        self.exclude_kw = exclude_kw or []
        self.feature_kw = feature_kw or []
        self.use_deepseek = use_deepseek
        self.max_len = max_len
        self.rows: list[dict] = []
        self.cleaned: list[dict] = []

    # ---------- 数据加载 ----------

    def load_csv(self, path: str, title_col: str = "title", company_col: str = "company",
                 desc_col: str = "description", location_col: str = "location", salary_col: str = "salary") -> int:
        p = Path(path)
        if not p.exists(): return 0
        count = 0
        with open(p, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                self.rows.append({"source": f"csv:{p.name}",
                                  "title": row.get(title_col, ""), "company": row.get(company_col, ""),
                                  "description": row.get(desc_col, ""),
                                  "location": row.get(location_col, ""), "salary": row.get(salary_col, "")})
                count += 1
        return count

    def load_markdown(self, path: str) -> int:
        p = Path(path)
        if not p.exists(): return 0
        try:
            sys.path.insert(0, str(ROOT))
            from report_utils import parse_table_rows
            count = 0
            for r in parse_table_rows(p.read_text(encoding="utf-8")):
                self.rows.append({"source": f"md:{p.name}", "title": r.get("position", ""),
                                  "company": r.get("company", ""), "description": "",
                                  "location": r.get("location", ""), "salary": ""})
                count += 1
            return count
        except ImportError:
            return self._md_fallback(p)

    def _md_fallback(self, p: Path) -> int:
        count = 0; in_table = False
        for line in p.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if line.startswith("|") and "公司" in line: in_table = True; continue
            if line.startswith("|---"): continue
            if in_table and line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 3:
                    self.rows.append({"source": f"md:{p.name}", "title": cells[2], "company": cells[1],
                                      "description": "", "location": cells[3] if len(cells)>3 else "", "salary": ""})
                    count += 1
            elif in_table and not line.startswith("|"): in_table = False
        return count

    def load_dicts(self, items: list[dict]) -> int:
        """直接从 dict 列表加载"""
        self.rows.extend(items)
        return len(items)

    # ---------- 清洗 ----------

    def clean_and_filter(self, deepseek_key: str = "") -> int:
        seen = set(); cleaned = []
        for row in self.rows:
            key = f"{_normalize(row['title'])}|{_normalize(row.get('company',''))}"
            if key in seen: continue
            seen.add(key)
            combined = f"{row['title']} {row.get('description','')}".lower()
            if any(kw in combined for kw in self.exclude_kw): continue
            desc = row.get("description", "")
            if self.use_deepseek and len(desc) > 100:
                row["description_clean"] = _call_deepseek_preprocess(desc, "denoise", deepseek_key)
                row["keywords"] = _call_deepseek_preprocess(desc, "keywords", deepseek_key)
            else:
                row["description_clean"] = desc
                found = [kw for kw in self.feature_kw if kw.lower() in desc.lower()]
                row["keywords"] = ", ".join(found) if found else desc[:200]
            row["text"] = f"{row['title']} {row['company']} {row.get('description_clean', desc)}"
            cleaned.append(row)
        self.cleaned = cleaned
        return len(cleaned)

    # ---------- 构建训练数据 ----------

    def build(self, text_a: str, val_split: float = 0.2, seed: int = 42) -> dict:
        """
        构建训练/验证数据。

        Args:
            text_a: Text A (e.g., resume)
            val_split: validation ratio

        Returns:
            {"train": (a_ids, b_ids, labels), "val": (...), "vocab_size": N, "max_len": L}
        """
        import torch
        from model.inference import text_to_ids, _pad_tensor

        if not self.cleaned: self.clean_and_filter()

        a_kw = set(kw for kw in self.feature_kw if kw.lower() in text_a.lower())
        a_ids_list = []; b_ids_list = []; labels = []

        for row in self.cleaned:
            jd = row.get("text", row.get("title", ""))
            if not jd.strip(): continue
            a_ids_list.append(text_to_ids(text_a, self.max_len))
            b_ids_list.append(text_to_ids(jd, self.max_len))
            jd_kw = set(k.strip() for k in row.get("keywords", "").split(",") if k.strip())
            hits = len(a_kw & jd_kw)
            score = min(95, max(10, int(hits / max(len(a_kw), 1) * 80 + 15)))
            labels.append(score)

        if not labels:
            raise ValueError("No training data found! Load data first.")

        n = len(labels)
        idx = np.random.RandomState(seed).permutation(n)
        s = int(n * (1 - val_split))

        a_ids = _pad_tensor(a_ids_list, self.max_len)
        b_ids = _pad_tensor(b_ids_list, self.max_len)
        y = torch.tensor(labels, dtype=torch.float32)

        # Determine vocab size from inference module
        from model.inference import VOCAB_SIZE as vs
        vocab_size = vs

        return {
            "train": (a_ids[idx[:s]], b_ids[idx[:s]], y[idx[:s]]),
            "val": (a_ids[idx[s:]], b_ids[idx[s:]], y[idx[s:]]),
            "vocab_size": vocab_size, "max_len": self.max_len,
            "n_train": s, "n_val": n - s,
        }

    @property
    def summary(self) -> dict:
        return {"raw": len(self.rows), "cleaned": len(self.cleaned)}
