# 真实语料检索评测（2026-10-20）

> **nDCG 更正（2026-10-21）**：本文 nDCG 数值由旧 scorer 计算，已确认系统性高估；
> 更正后的数值与重算方法见 [ndcg-correction-2026-10-21.md](ndcg-correction-2026-10-21.md)。
> 本文保留原值作为历史记录，Recall/MRR 不受影响。

本文件记录**三份真实标准、70 题**的 chunk 级检索评测。它是工程实测，不是人工 gold 的最终结论。

## 1. 结论先行

- 在这批 67 道可回答题上，**Hybrid + BGE-Reranker 的 Recall/nDCG/MRR 最高**；但 BM25 的 nDCG@10 只低 0.0026，且耗时约为 reranker 的 1/58。结果对语料/干扰项敏感：上一版两文档数据中 reranker 并未超过 BM25。
- Query IR（别名扩展/规格归一化）对 Dense 与 Hybrid 有小幅提升，对 BM25 和已开启 reranker 的 Hybrid 没有可见提升。
- Contextual Retrieval 的 70 题同 qrels 消融中，Dense/Hybrid 的 top-10 排序明显提升（Hybrid Recall@5 +0.0721），但 BGE reranker 的 Recall@5 小幅回退 0.0050、nDCG@10 提升 0.0195；因此**默认仍关闭**，不能宣称全面胜出。
- 3 道“资料不足”题中 2 道被正确拒答；R064（禁用渔药清单）被误答，说明词面 gate 不是语义蕴含判断。
- 所有 56 个唯一 gold child chunk 都能在 Qdrant 中找到；54 个 gold parent chunk 按设计不是独立 point，评测按“返回给 LLM 的 parent 上下文”计主指标，并另报 child 精确指标。

## 2. 数据集与索引

| 项 | 值 |
|---|---|
| 题集 | `eval/real_questions_v1.jsonl` |
| 题数 | 70（67 可回答 + 3 资料不足） |
| 标注状态 | `ai_assisted_pending_human_review`，**不是人工确认的 ground truth** |
| 文档 | DB36/T 2225—2026 中华绒螯蟹（9 页，34 child chunks）；DB46 南美白对虾征求意见稿（18 页，109 child chunks）；DB32/T 5292—2025 中华绒螯蟹生态育苗（7 页，35 child chunks） |
| 索引 | `kb_chunks_bge_m3_v1`，6 个 active 文档、190 个 child points |
| Contextual 索引 | `kb_chunks_bge_m3_ctx_v1`，同一批 190 points；dense 用 `context_text`，BM25 仍用 raw content |
| Dense | BGE-M3，1024 维，Cosine |
| Sparse | 应用侧 jieba + 自定义词，Qdrant `bm25` sparse，`modifier=IDF` |
| Hybrid | RRF，`rrf_k=60`，dense/BM25 各取 20 |
| Reranker | `BAAI/bge-reranker-v2-m3`，本机 MPS/fp16 |
| 数据集 SHA-256 | `09d2a329e9710ae1d3e212b1b927e3ee06bc2a93b5638d2bf2d2e564d6eb01ca` |

题目、页码、child chunk、parent chunk、证据句和评分均由 `scripts/build_real_eval_dataset.py` 从数据库中已解析的真实 PDF 块解析生成。`gold` 中的 `grade=2` 表示直接答案，`grade=1` 表示支撑/对照证据。**题集尚未经过第二人复核**，不能称为人工 qrels。

## 3. 指标定义

- **Recall@K**：gold 中被前 K 个结果覆盖的比例；多 gold 题按比例计。
- **nDCG@K**：按 `grade` 计算，`DCG = Σ(2^g-1)/log2(rank+1)`，IDCG 用同一题 gold 的理想排序。
- **MRR@10**：第一个相关结果排名的倒数；无相关结果为 0。
- **主指标（parent）**：系统返回给 LLM 的上下文单元是 parent chunk，因此主表用 parent chunk ID 对齐 gold parent；这比 child 指标更接近最终生成看到的证据。
- **child 指标**：用代表 child chunk 精确对齐，更严格，列在 `child_*`。
- 拒答按 0 计入可回答题的均值；资料不足题单独统计拒答通过率，不混入检索均值。

## 4. 结果 A：系统默认开启 Query IR

运行参数：`--query-ir`，`query_planner=false`，`contextual_retrieval=false`，`top_k=10`。

| mode | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 | MRR@10 | child Recall@10 | child nDCG@10 | child MRR@10 | 平均耗时 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Dense | 0.8632 | 0.8781 | 0.8714 | 0.8863 | 0.7736 | 0.8284 | 0.8482 | 0.7475 | 69.5 |
| BM25 | 0.8507 | 0.9279 | 0.8507 | 0.9328 | 0.8113 | 0.7910 | 0.8582 | 0.7494 | 18.1 |
| Hybrid | 0.8582 | 0.8831 | 0.8631 | 0.8881 | 0.8226 | 0.8433 | 0.8509 | 0.8050 | 55.0 |
| Hybrid + Reranker | **0.8980** | **0.9353** | **0.9030** | **0.9354** | **0.8488** | **0.8781** | **0.8983** | **0.8273** | 1043.8 |

说明：

- Reranker 在本版三文档语料上拿到最高的 parent Recall@5/@10、nDCG@5/@10 和 MRR；BM25 的 nDCG@10 仅低 0.0026，但 Recall@5 低 0.0473，说明 BM25 把部分正确证据排到 5 名之后。
- Hybrid 的 MRR（0.8226）高于 BM25（0.8113），但 Recall@10 不到 0.89，仍弱于 BM25 的 0.9279。
- Reranker 的 child 指标也全面领先；延迟从 18.1 ms 增至 1043.8 ms（约 58×，含本机 MPS 推理）。这是离线批量、单请求串行的测量，不是线上 P95。
- **没有一种模式全面胜出**：上一版两文档语料中 BM25 的 nDCG@10 最高，本版加入 DB32 干扰项后 reranker 领先；结果对语料与候选池敏感，不能据此宣称通用优越性。
- 本表 Dense 有 1 道可回答题（R061，跨 DB36/DB46 的溶解氧对比）因 Query IR 变体证据未覆盖而被 gate 拒答；其余模式在 67 道可回答题上均未拒答。该题按 0 计入 Dense 均值。

## 5. 结果 B：关闭 Query IR 的消融

同题集、同索引，仅关闭 Query IR（纯 Dense/BM25/RRF）。用于区分“检索器本身”和“查询改写”的贡献。

| mode | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 | MRR@10 | 平均耗时 ms |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.8333 | 0.8483 | 0.8415 | 0.8565 | 0.7345 | 48.1 |
| BM25 | 0.8507 | 0.9279 | 0.8507 | 0.9328 | 0.8113 | 17.8 |
| Hybrid | 0.8582 | 0.8731 | 0.8631 | 0.8780 | 0.7923 | 47.3 |
| Hybrid + Reranker | 0.8980 | 0.9353 | 0.9030 | 0.9354 | 0.8488 | 1033.0 |

Query IR 使 Dense 的 Recall@10 从 0.8483 升到 0.8781，Hybrid 从 0.8731 升到 0.8831；BM25 不变（其查询词未被别名扩展改变），reranker 的 parent 指标也不变。该提升幅度只对应这批题和这套规则，不能外推。


### 5.1 Contextual Retrieval 同题消融

同一 70 题、同一 gold、同一 BGE-M3/BGE-Reranker，只把 dense 输入从原始 chunk 换成 `context_text`（`kb_chunks_bge_m3_ctx_v1`，190 points）；BM25 仍对原始 content 建稀疏向量。这是当前唯一一次 70 题同 qrels 的 Contextual 消融，不是小样本 smoke。

**Query IR 开启：**

| mode | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 | MRR@10 | 平均耗时 ms |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.9005 | 0.9279 | 0.9080 | 0.9308 | 0.8230 | 55.1 |
| BM25 | 0.8657 | 0.9279 | 0.8657 | 0.9328 | 0.8120 | 15.5 |
| Hybrid | 0.9303 | 0.9353 | 0.9379 | 0.9431 | 0.8383 | 55.1 |
| Hybrid + Reranker | 0.8930 | 0.9502 | 0.8957 | 0.9549 | 0.8566 | 1055.0 |

**Query IR 关闭：**

| mode | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 | MRR@10 | 平均耗时 ms |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.9005 | 0.9353 | 0.9080 | 0.9399 | 0.8227 | 47.6 |
| BM25 | 0.8657 | 0.9279 | 0.8657 | 0.9328 | 0.8192 | 15.8 |
| Hybrid | 0.9303 | 0.9353 | 0.9434 | 0.9452 | 0.8264 | 46.7 |
| Hybrid + Reranker | 0.8930 | 0.9502 | 0.8957 | 0.9549 | 0.8488 | 1055.5 |

与第 4、5 节的同题 raw 结果相比：

- Dense Recall@5：QIR 0.8632 → 0.9005（+0.0373），no-QIR 0.8333 → 0.9005（+0.0672）；QIR 下 Dense 的 1 次错误拒答（R061）也消失。
- Hybrid Recall@5：QIR 0.8582 → 0.9303（+0.0721），no-QIR 0.8582 → 0.9303（+0.0721）；nDCG@10 分别 +0.0550 / +0.0672。
- Reranker：Recall@5 从 0.8980 降到 0.8930（-0.0050），但 Recall@10 +0.0149、nDCG@10 +0.0195；说明 contextual 让候选更靠前，却让 reranker 在少数题上把另一个相关段排到 top5 外。不能只说“reranker 更强”。
- BM25 的 sparse 向量仍来自 raw content，理论上应与 raw collection 完全一致；观测到 0.8507 → 0.8657 的小差异，可能来自重建时的候选点/版本组成或运行状态，**不能归因于 contextual**。R064 的清单完整性失败在两种 collection 都存在，3 题不足题仍只正确拒答 2 题。
- 这不是“Contextual 全面胜出”：reranker Recall@5 有小幅回退，且 gold 仍是 AI 辅助、待人工复核。因此默认仍关闭 `ENABLE_CONTEXTUAL_RETRIEVAL`；本消融只证明 **dense/hybrid 的 top-10 排序有明显提升，reranker 需单独决策**。

复现：

```bash
QDRANT_COLLECTION=kb_chunks_bge_m3_ctx_v1 \
  .venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --contextual --query-ir --out ../../eval/runs/real_questions_v1_1_ctx_query_ir
```

## 6. 拒答与失败分析

### 6.1 资料不足题

3 题中 2 题被正确拒答（天气、补贴）；R064（“禁用渔药清单”）被四种模式都放行。R064 的问题包含“渔药”等领域词，而知识库只有零散用药段落，没有完整禁用清单；词面 gate 把“相关”误当成“充分”。这是一个真实的**证据充分性失败**，不能用“已经检索到渔药段落”掩盖。

### 6.2 可回答题的典型失败

| 题号 | 问题 | 现象 | 归因 |
|---|---|---|---|
| R001 | DB36 规程适用范围 | BGE reranker 未进 top5，其他模式命中 | reranker 对长“范围”段落降权 |
| R006 | 蟹苗来源 | 四种模式均未命中 gold | 查询词短、通用词“来源”稀释，child 排序弱 |
| R014 | 水质指标 | BM25 第 9、Hybrid 第 10、reranker 第 7 | 多个水质段落竞争，top5 挤掉正确段 |
| R024 | 池塘条件 | 前三种第 6–8；reranker 第 4 | reranker 在本题有实际收益 |
| R026 | 对虾盐度/pH/溶氧 | Dense/Hybrid 未命中，BM25/reranker 第 2 | 词面信号强，dense 语义排序不占优 |
| R035 | 渔药使用规定 | BM25 第 1，reranker 未命中 | reranker 误排 |
| R039 | 亲本雌雄配比 | 四种模式均未进 top10 | “雌雄配比”切词/索引词不匹配 |
| R061 | DB36 与 DB46 溶解氧是否一致 | 均只覆盖单侧，跨文档失败 | 缺少真正的多文档证据聚合 |
| R062 | 两品种 pH 差异 | 最好 2/3 gold，交叉文档部分命中 | 跨文档 + 多证据 |
| R066 | DB32 水温和 pH | Dense 未进 top5，其余模式命中 | DB32 新增干扰项，dense 排序不稳 |
| R068 | DB32 亲蟹体重/肥满度 | BM25 未进 top5，Dense/Hybrid/Reranker 命中 | “肥满度/体重”词面信号弱 |

这些失败没有被“平均分”掩盖；它们指向下一阶段的具体工作：查询词/领域词典、跨文档证据聚合、reranker 候选与排序诊断。

## 7. 可复现实验

```bash
cd apps/api

# 系统默认（Query IR 开）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --query-ir --out ../../eval/runs/real_questions_v1_1_query_ir

# 消融（Query IR 关）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --out ../../eval/runs/real_questions_v1_1_no_query_ir
```

产物：

- `eval/runs/real_questions_v1_1_query_ir/{details.jsonl,summary.csv,manifest.json}`
- `eval/runs/real_questions_v1_1_no_query_ir/{details.jsonl,summary.csv,manifest.json}`
- `eval/runs/real_questions_v1_1_ctx_query_ir/{details.jsonl,summary.csv,manifest.json}`
- `eval/runs/real_questions_v1_1_ctx_no_query_ir/{details.jsonl,summary.csv,manifest.json}`

`manifest.json` 记录数据 hash、模型、collection、`query_ir` 开关和 git commit；`details.jsonl` 保留逐题排名、gold 排名和拒答原因。

## 8. 限制

1. **只有 3 份真实标准**，190 个 child points；不能代表通用水产养殖语料。
2. **gold 是 AI 辅助构建、待人工复核**，不是人工 qrels；`grade=1/2` 尚未经过第二人校准。
3. 主指标是 parent 级，相对 child 级偏宽；child 指标已同时报告，避免只挑好看的数。
4. 单机单次运行，无置信区间/显著性检验；耗时受 MPS、缓存和并发影响。
5. PDF 表格/页眉切分仍可能造成 gold 证据不完整；R006/R039 的“未命中”可能同时包含索引词和切分因素。
6. 本评测不调用生成模型，不能说明最终答案事实正确；生成质量需另做人工/自动校验。
