# nDCG 计算更正与历史结果重算（2026-10-21）

## 1. 问题

`score_ranking` 在计算 DCG 前先过滤掉不相关项：

```python
gained = [gold[chunk_id] for chunk_id in ranked[:k] if chunk_id in gold]   # 旧
```

这会把原本排在第 2、第 5 的相关项重新当成第 1 名计分，DCG 被系统性高估；
排序越靠前插入的无关项越多，虚高越明显。Recall、MRR、`first_relevant_rank`
不经过这段逻辑，因此不受影响。

审计给出的最小反例：排名 `["wrong", "correct"]`、`gold={"correct": 2}`，
旧实现给 nDCG=1.0；正确值 `1/log2(3)=0.6309`。

## 2. 修复

- `apps/api/app/evaluation/retrieval_metrics.py`：改为按原位置取分
  `gained = [gold.get(chunk_id, 0) for chunk_id in ranked[:k]]`；重复 ID 在入口去重，
  避免同一相关项被重复计分导致 nDCG>1。
- `scripts/evaluate_retrieval_metrics.py`：删除重复实现，统一 import 该 scorer。
- 新增测试 `test_ndcg_penalises_irrelevant_hits_in_place`（上例 0.6309、插入更多无关项
  继续下降）与 `test_ndcg_respects_grades_and_dedupes_ranked_ids`（grade、交换、重复 ID）。

## 3. 用已保存排名重算（不重新检索、不调 LLM）

```bash
cd apps/api
.venv/bin/python ../../scripts/recompute_ndcg.py
# 结果写入 eval/runs/ndcg_recompute.json
```

### 3.1 67 道可回答题、Query IR 开（原 `retrieval-evaluation` 表 A）

| mode | nDCG@5 旧 | nDCG@5 新 | nDCG@10 旧 | nDCG@10 新 |
|---|---:|---:|---:|---:|
| Dense | 0.8714 | 0.7923 | 0.8863 | 0.7976 |
| BM25 | 0.8507 | 0.8122 | 0.9328 | 0.8398 |
| Hybrid | 0.8631 | 0.8294 | 0.8881 | 0.8380 |
| Hybrid + Reranker | 0.9030 | **0.8562** | 0.9354 | **0.8675** |

结论变化：旧表里“BM25 的 nDCG@10 只比 reranker 低 0.0026”不再成立，新值是
**0.0277**；reranker 在 nDCG 上的领先被旧实现压平了。

### 3.2 关闭 Query IR 的消融（原表 B）

| mode | nDCG@5 旧 | nDCG@5 新 | nDCG@10 旧 | nDCG@10 新 |
|---|---:|---:|---:|---:|
| Dense | 0.8415 | 0.7568 | 0.8565 | 0.7618 |
| BM25 | 0.8507 | 0.8122 | 0.9328 | 0.8398 |
| Hybrid | 0.8631 | 0.8079 | 0.8780 | 0.8132 |
| Hybrid + Reranker | 0.9030 | **0.8562** | 0.9354 | **0.8675** |

### 3.3 Contextual 消融（67 可回答题，`ctx_query_ir` vs `query_ir`）

| mode | raw nDCG@10 旧 | raw 新 | ctx nDCG@10 旧 | ctx 新 | 新差值 |
|---|---:|---:|---:|---:|---:|
| Dense | 0.8863 | 0.7976 | 0.9308 | 0.8450 | +0.0474 |
| Hybrid | 0.8881 | 0.8380 | 0.9431 | 0.8560 | +0.0180 |
| Hybrid + Reranker | 0.9354 | 0.8675 | 0.9549 | 0.8769 | +0.0094 |

方向仍是 contextual 正向，但 reranker 的增益从 +0.0195 缩小到 +0.0094；
“contextual 让 reranker 排序大幅提升”的说法应降级为“小幅提升”。

### 3.4 70 题规则 vs LLM（`planner_retrieval_ab_70_v5.json`）

| 指标 | 规则 IR（70） | LLM IR（70） | 规则 IR（65 作答） | LLM IR（65 作答） |
|---|---:|---:|---:|---:|
| nDCG@5 | 0.8105 | 0.7780 | 0.8728 | 0.8378 |
| nDCG@10 | 0.8213 | 0.7912 | 0.8845 | 0.8520 |

规则 IR 领先的结论不变，差距比旧值（0.8500 vs 0.8313）更大。

### 3.5 未受影响的表

- R061（`r061_source_aware`）：nDCG@5/@10 重算仍为 **1.0 / 1.0**。
- 所有 Recall、MRR、拒答率、耗时数字不变。

## 4. 处理原则

旧数值保留在 `eval/runs/*/summary.json` 与历史文档中作对照，不覆盖；引用 nDCG 时
以本文件与 `eval/runs/ndcg_recompute.json` 为准。完整逐 run/逐 mode 的旧值、新值、
差值在重算 JSON 里，本文只列主要表格。