# 实验结果汇总 v1（2026-10-22）

四组实验的紧凑结果归档。完整明细在 `eval/runs/`（本地，gitignore）；本目录只保留
汇总表、清单和解读，便于论文引用与复现核对。

| 实验 | 数据 | 报告 | 关键结果 |
|---|---|---|---|
| 检索四组对比 | 100 题中文 | [retrieval_report.md](retrieval_report.md) / [retrieval_analysis.md](retrieval_analysis.md) | rerank R@10 **0.680**，nDCG@10 **0.549**；四组单调改进 |
| 引用一致性 | 50 条答案 | [citation_analysis.md](citation_analysis.md) | 引用覆盖 **0.691**，非法引用 0，词面支持 **89.5%** |
| 拒答测试 | 30 题 | [refusal_analysis.md](refusal_analysis.md) | 拒答率 **0.60**；域内无依据仅 3/10 |
| 覆盖矩阵 | 1548 篇 | [coverage_matrix_v1.md](coverage_matrix_v1.md) | 来源×主题×可检索/已隔离/总数 |

## 检索（父块，top_k=10）

| 模式 | R@5 | R@10 | nDCG@10 | MRR@10 | 平均耗时 |
|---|---|---|---|---|---|
| dense | 0.410 | 0.480 | 0.349 | 0.307 | 138 ms |
| bm25 | 0.460 | 0.540 | 0.389 | 0.342 | 90 ms |
| hybrid RRF | 0.510 | 0.610 | 0.442 | 0.390 | 127 ms |
| + reranker | **0.600** | **0.680** | **0.549** | **0.508** | 2 681 ms |

分层结论（详见 analysis）：

- 标准题 BM25 R@10 0.793 > dense 0.310——标准号在块文本里逐字出现，词法占优；
- 地方题 dense 0.806 > BM25 0.556——口语化技术文章更依赖语义；
- 国家级预报四组全部 ≤0.250——块文本没有省份/月份，索引层缺元数据，属系统缺陷；
- reranker 把期刊题从 0.467 提到 0.733，但延迟升到 2.7 s。

## 引用

- 50 条答案全部出答，引用覆盖率 0.691，非法编号 0；
- 429 个带引用句子中 384 个（89.5%）能在所引父块中找到词面依据；
- 150 个“事实型”句子没有引用；45 个引用句词面不重合，需逐条人工判读；
- 该 89.5% 是词面支持下界，**不能写成引用准确率**。

## 拒答

| 类别 | 拒答率 |
|---|---|
| 完全域外 | 0.80 |
| 邻近农业 | 0.70 |
| 域内但无依据 | 0.30 |
| 合计 | 0.60 |

误答根因：语料混入非水产文档（肉鸡、种植业）、虚构标准号/未来年份无实体校验、
门禁阈值偏松（0.04–0.20 仍放行）。详见 refusal_analysis。

## 覆盖

- active 1548，eligible 1347，隔离 200，ineligible 1；
- 国家级推广 459 篇中 448 篇是病害预报，主题高度单一；
- WorldFish 723 篇中 526 篇可检索，按主题分散；
- 地方 222 篇中 142 篇落在“其他”，主题标注仍需人工。

## 复现

```bash
cd apps/api
.venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --dataset ../../eval/retrieval_eval_100_v1.jsonl --out ../../eval/runs/retrieval_100_v1
.venv/bin/python ../../scripts/report_retrieval_eval.py
.venv/bin/python ../../scripts/evaluate_refusal.py
.venv/bin/python ../../scripts/coverage_matrix.py
.venv/bin/python ../../scripts/evaluate_answer_quality.py \
  --dataset ../../eval/retrieval_eval_100_v1.jsonl --ids $(...) --families rules
.venv/bin/python ../../scripts/analyze_citations.py
```

数据集与快照的 sha 记录在各 `*_manifest.json`；本轮 git 提交见 `git log`。

## 效度边界（写论文必须带上）

1. 100 题仍是模板生成、待人工终审；标准题引用标准号，BM25 有利。
2. 全部中文，未覆盖 526 篇英文 WorldFish，总体指标不代表全库。
3. 引用支持是 4-gram 词面代理，不是蕴含判断。
4. 拒答只测检索门禁，不测模型在证据不足时是否自行 abstain。
5. 语料主题不纯（肉鸡/种植业文档）会同时抬高覆盖数字和误答率。