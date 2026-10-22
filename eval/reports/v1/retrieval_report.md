# 检索评测 v1（100 题中文）

- 数据集：`../../eval/retrieval_eval_100_v1.jsonl`（sha256 `acad2c3dff726e27…`）
- 集合：`kb_chunks_bge_m3_v1`，embedding `BAAI/bge-m3`，reranker `BAAI/bge-reranker-v2-m3`
- top_k=10，模式：dense, bm25, hybrid, hybrid_rerank，git `26234ec0`
- 指标：父块（送入 LLM 的上下文单元）为主，`child_*` 为代表性子块；拒答按 0 分计入。

## 总体

| 模式 | R@5 | R@10 | nDCG@5 | nDCG@10 | MRR@10 | 平均耗时(ms) | 拒答 |
|---|---|---|---|---|---|---|---|
| dense | 0.41 | 0.48 | 0.3246 | 0.3485 | 0.307 | 137.8 | 7 |
| bm25 | 0.46 | 0.54 | 0.3631 | 0.3889 | 0.3422 | 89.7 | 0 |
| hybrid | 0.51 | 0.61 | 0.4105 | 0.4419 | 0.3896 | 127.1 | 0 |
| hybrid_rerank | 0.6 | 0.68 | 0.5223 | 0.5493 | 0.508 | 2681.3 | 0 |

### 按来源

| 分组 | n | 模式 | R@5 | R@10 | nDCG@10 | MRR@10 |
|---|---|---|---|---|---|---|
| journal | 15 | dense | 0.400 | 0.467 | 0.351 | 0.315 |
| journal | 15 | bm25 | 0.400 | 0.667 | 0.329 | 0.230 |
| journal | 15 | hybrid | 0.400 | 0.467 | 0.332 | 0.290 |
| journal | 15 | hybrid_rerank | 0.667 | 0.733 | 0.524 | 0.458 |
| local | 36 | dense | 0.667 | 0.806 | 0.592 | 0.524 |
| local | 36 | bm25 | 0.472 | 0.556 | 0.394 | 0.344 |
| local | 36 | hybrid | 0.639 | 0.778 | 0.558 | 0.489 |
| local | 36 | hybrid_rerank | 0.694 | 0.806 | 0.628 | 0.573 |
| national | 20 | dense | 0.150 | 0.150 | 0.064 | 0.037 |
| national | 20 | bm25 | 0.000 | 0.050 | 0.017 | 0.007 |
| national | 20 | hybrid | 0.050 | 0.150 | 0.080 | 0.061 |
| national | 20 | hybrid_rerank | 0.100 | 0.250 | 0.109 | 0.065 |
| standard | 29 | dense | 0.276 | 0.310 | 0.242 | 0.220 |
| standard | 29 | bm25 | 0.793 | 0.793 | 0.670 | 0.630 |
| standard | 29 | hybrid | 0.724 | 0.793 | 0.604 | 0.544 |
| standard | 29 | hybrid_rerank | 0.793 | 0.793 | 0.768 | 0.759 |

### 按题型

| 分组 | n | 模式 | R@5 | R@10 | nDCG@10 | MRR@10 |
|---|---|---|---|---|---|---|
| forecast | 20 | dense | 0.150 | 0.150 | 0.064 | 0.037 |
| forecast | 20 | bm25 | 0.000 | 0.050 | 0.017 | 0.007 |
| forecast | 20 | hybrid | 0.050 | 0.150 | 0.080 | 0.061 |
| forecast | 20 | hybrid_rerank | 0.100 | 0.250 | 0.109 | 0.065 |
| journal_conclusion | 15 | dense | 0.400 | 0.467 | 0.351 | 0.315 |
| journal_conclusion | 15 | bm25 | 0.400 | 0.667 | 0.329 | 0.230 |
| journal_conclusion | 15 | hybrid | 0.400 | 0.467 | 0.332 | 0.290 |
| journal_conclusion | 15 | hybrid_rerank | 0.667 | 0.733 | 0.524 | 0.458 |
| local_tech | 36 | dense | 0.667 | 0.806 | 0.592 | 0.524 |
| local_tech | 36 | bm25 | 0.472 | 0.556 | 0.394 | 0.344 |
| local_tech | 36 | hybrid | 0.639 | 0.778 | 0.558 | 0.489 |
| local_tech | 36 | hybrid_rerank | 0.694 | 0.806 | 0.628 | 0.573 |
| standard_section | 29 | dense | 0.276 | 0.310 | 0.242 | 0.220 |
| standard_section | 29 | bm25 | 0.793 | 0.793 | 0.670 | 0.630 |
| standard_section | 29 | hybrid | 0.724 | 0.793 | 0.604 | 0.544 |
| standard_section | 29 | hybrid_rerank | 0.793 | 0.793 | 0.768 | 0.759 |

