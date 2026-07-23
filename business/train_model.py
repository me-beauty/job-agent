#!/usr/bin/env python3
"""
模型训练 v2 — 合成标签覆盖 5-95 全范围，让模型学会真正区分匹配等级。

策略：
  完美匹配 (85-95): 技能+地点+公司全中
  良好匹配 (60-80): 技能匹配，地点近
  一般匹配 (35-55): 部分技能匹配
  弱匹配   (15-30): 几乎没有共同点
  不匹配   ( 5-15): 完全无关

用法:
  python -m business.train_model
  或通过 API: POST /api/train_match_model
"""

import random, time
import numpy as np

from utils.logger import get_logger

logger = get_logger("business.train")

# 技能池
DATA_SKILLS = ['Python','SQL','数据分析','Pandas','NumPy','Spark','Hadoop',
               'TensorFlow','PyTorch','数据可视化','Excel','深度学习','NLP',
               'Django','Flask','Java','ETL','Docker','Kubernetes','Kafka','Redis',
               'MySQL','Linux','Git','Tableau','Scikit-learn']
SOFT_SKILLS = ['机器学习','数据挖掘','数据仓库','数据治理','统计学','数学建模',
               '计算机视觉','推荐系统','NLP','AB测试','特征工程','模型部署']

CITIES = ['石家庄','保定','唐山','北京','天津','廊坊']
DEGREES = ['数据科学本科','计算机本科','统计学本科','大数据本科','信息管理本科']


def _generate_dataset(n=6000):
    """生成 5-95 全覆盖数据集"""
    from business.match_scorer import _get_fallback, _rule_score
    from business.collector import _known_companies
    scorer = _get_fallback()

    # Job pool (real company names + realistic descriptions)
    companies = _known_companies()
    job_pool = []
    for company, loc, url, priority in companies:
        for role, kws, is_tech in [
            ('数据分析实习生', 'Python SQL Pandas 数据可视化 Excel 统计学 AB测试', True),
            ('大数据开发实习生', 'Spark Hadoop Hive Kafka Java Scala ETL 数据仓库', True),
            ('机器学习实习生', 'Python PyTorch TensorFlow 深度学习 NLP 特征工程 模型部署', True),
        ]:
            job_pool.append({
                'text': f'{role} {company} {loc} {kws}',
                'tech': is_tech,
                'company': company,
                'loc': loc,
                'skills': kws.split(),
            })

    # Unrelated job pool for negative samples
    neg_jobs = [
        '销售代表 XX销售公司 北京 负责产品销售和客户开发 无技术门槛',
        '房产中介 链家地产 石家庄 二手房买卖租赁 高提成',
        '客服专员 XX客服中心 保定 接听客户电话 处理投诉',
        '餐厅服务员 XX酒店 唐山 点菜上菜 卫生打扫',
        '保安 XX物业 石家庄 小区巡逻 门岗值班',
        '快递员 顺丰速运 北京 收派快递 区域配送',
        '工厂操作工 XX制造厂 保定 流水线操作 机器看护',
        '文员 XX贸易公司 石家庄 文档整理 会议安排 快递收发',
    ]

    all_r, all_j, all_s = [], [], []

    def add(resume, job, score):
        all_r.append(resume)
        all_j.append(job['text'] if isinstance(job, dict) else job)
        all_s.append(float(np.clip(score, 5, 95)))

    def make_resume():
        n = random.randint(4, 10)
        skills = random.sample(DATA_SKILLS, n)
        city = random.choice(CITIES)
        degree = random.choice(DEGREES)
        year = random.choice(['2027届','应届','大三','大四'])
        tmpl = random.choice([
            '{skills} {degree} {year} 找{city}实习',
            '{year} {degree} 熟悉{skills} 期望在{city}工作',
            '求职：{city}实习 | {degree} | 技术栈：{skills}',
            '{degree} {year}毕业生 掌握{skills} 找{city}及周边实习',
        ])
        return tmpl.format(skills=' '.join(skills), degree=degree, year=year, city=city), skills

    # === Tier 1: 完美匹配 (85-95) ===
    for _ in range(n // 6):
        resume, rskills = make_resume()
        # Find job with max overlap
        best_job = None
        best_overlap = 0
        for job in job_pool:
            if not job['tech']:
                continue
            overlap = len(set(s.lower() for s in rskills) & set(s.lower() for s in job['skills']))
            if overlap > best_overlap:
                best_overlap = overlap
                best_job = job
        if best_job and best_overlap >= 4:
            add(resume, best_job, random.uniform(85, 95))

    # === Tier 2: 良好匹配 (60-80) ===
    for _ in range(n // 5):
        resume, rskills = make_resume()
        tech_jobs = [j for j in job_pool if j['tech']]
        job = random.choice(tech_jobs)
        overlap = len(set(s.lower() for s in rskills) & set(s.lower() for s in job['skills']))
        base = 55 + overlap * 4
        # Location bonus
        resume_city = next((c for c in CITIES if c in resume), '北京')
        if resume_city in job['loc']:
            base += 10
        add(resume, job, random.uniform(base, base + 8))

    # === Tier 3: 一般匹配 (35-55) ===
    for _ in range(n // 4):
        resume, rskills = make_resume()
        job = random.choice(job_pool)
        overlap = len(set(s.lower() for s in rskills) & set(s.lower() for s in job.get('skills', [])))
        base = 25 + overlap * 5
        add(resume, job, random.uniform(base, base + 10))

    # === Tier 4: 弱匹配 (15-30) ===
    for _ in range(n // 6):
        resume, rskills = make_resume()
        # Assign a tech job in wrong city with minimal skill overlap
        job = random.choice(job_pool)
        # Force weak score
        add(resume, job, random.uniform(15, 30))

    # === Tier 5: 不匹配 (5-15) ===
    for _ in range(n // 6):
        resume, _ = make_resume()
        job_text = random.choice(neg_jobs)
        add(resume, {'text': job_text, 'tech': False, 'skills': []},
            random.uniform(3, 12))

    logger.info(f'Train data: {len(all_s)} pairs | range {min(all_s):.0f}-{max(all_s):.0f}')

    # Print distribution
    bins = [0, 20, 40, 60, 80, 100]
    dist = {}
    for s in all_s:
        for i in range(len(bins) - 1):
            if bins[i] <= s < bins[i + 1]:
                dist[f'{bins[i]}-{bins[i+1]}'] = dist.get(f'{bins[i]}-{bins[i+1]}', 0) + 1
                break
    logger.info(f'Distribution: {dist}')

    return all_r, [j['text'] if isinstance(j, dict) else j for j in all_j], \
           np.array(all_s, dtype=np.float32)


def train_model(epochs=25, lr=0.003, batch_size=128):
    import torch
    from model.inference import text_to_ids, MatchInference
    from model.trainer import MatchTrainer

    MAX_LEN = 64
    EMBED_DIM = 64
    HIDDEN_DIM = 64

    def pad(ids_list, ml):
        arr = np.zeros((len(ids_list), ml), dtype=np.int64)
        for i, ids in enumerate(ids_list):
            L = min(len(ids), ml)
            arr[i, :L] = ids[:L]
        return arr

    # 1. Generate data
    all_r, all_j, scores = _generate_dataset(5000)

    # 2. Vocab
    max_idx = 0
    for t in all_r + all_j:
        ids = text_to_ids(t, 10000)
        if ids:
            max_idx = max(max_idx, max(ids))
    vocab = max_idx + 1
    logger.info(f'vocab={vocab} max_len={MAX_LEN}')

    # 3. Tokenize
    r_ids = pad([text_to_ids(r, MAX_LEN) for r in all_r], MAX_LEN)
    j_ids = pad([text_to_ids(j, MAX_LEN) for j in all_j], MAX_LEN)

    # 4. Split
    n = len(scores)
    idx = np.random.permutation(n)
    sp = int(n * 0.85)
    tr_r = torch.tensor(r_ids[idx[:sp]], dtype=torch.long)
    tr_j = torch.tensor(j_ids[idx[:sp]], dtype=torch.long)
    tr_y = torch.tensor(scores[idx[:sp]], dtype=torch.float32)
    vl_r = torch.tensor(r_ids[idx[sp:]], dtype=torch.long)
    vl_j = torch.tensor(j_ids[idx[sp:]], dtype=torch.long)
    vl_y = torch.tensor(scores[idx[sp:]], dtype=torch.float32)

    logger.info(f'{len(tr_y)} train / {len(vl_y)} val')

    # 5. Train
    t0 = time.time()
    trainer = MatchTrainer(vocab_size=vocab, embed_dim=EMBED_DIM, hidden_dim=HIDDEN_DIM)
    result = trainer.fit((tr_r, tr_j, tr_y), (vl_r, vl_j, vl_y),
                         epochs=epochs, lr=lr, batch_size=batch_size)
    elapsed = time.time() - t0

    # 6. Test with MatchInference
    mi = MatchInference()
    mi.load(str(result['model_path']))

    print(f'\nTraining: {elapsed:.0f}s | {result["model_name"]} | MAE={result["val_mae"]:.1f} | Acc={result["accuracy"]:.1%}')
    print(f'\n--- Discrimination ---')

    test_cases = [
        ('Python SQL Pandas 数据分析 数据科学本科 北京实习',
         '数据分析实习生 字节跳动 北京 Python SQL Pandas 数据可视化 Excel 统计学 AB测试', 'good'),
        ('Python SQL Pandas 数据分析 数据科学本科 石家庄实习',
         '数据分析实习生 河北移动 石家庄 SQL Python 通信数据分析', 'good-local'),
        ('Python PyTorch TensorFlow 深度学习 NLP 计算机本科 北京实习',
         'ML实习生 快手 北京 PyTorch TensorFlow 深度学习 NLP 特征工程', 'good-ML'),
        ('Java Spring Hibernate 软件工程本科 北京实习',
         '数据分析实习生 字节跳动 北京 Python SQL Pandas', 'wrong-skills'),
        ('Python SQL 数据分析 Pandas 数据科学本科 北京实习',
         '销售代表 XX销售公司 北京 负责产品销售', 'unrelated'),
        ('Python SQL 数据分析 Pandas 数据科学本科 北京实习',
         '快递员 顺丰速运 北京 收派快递', 'totally-off'),
    ]
    for rs, jb, label in test_cases:
        sc = mi.score(rs, jb)
        bar = '█' * int(sc / 5)
        print(f'  [{label:12s}] score={sc:3.0f} {bar}')

    return result


if __name__ == "__main__":
    train_model()
