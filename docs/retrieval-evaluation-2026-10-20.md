# 真实语料检索评测（2026-10-20）

本文件记录第一版**真实两文档、65 题**的 chunk 级检索评测。它是工程实测，不是人工 gold 的最终结论。

## 1. 结论先行

- 在这批 62 道可回答题上，**BM25 的 nDCG@10 最高（0.9452）**，Hybrid 的 MRR 最高（0.8620），BGE-Reranker 没有稳定超过 BM25，且平均检索耗时约为 BM25 的 56 倍。
- Query IR（别名扩展/规格归一化）对 Dense 与 Hybrid 有小幅提升，对 BM25 和已开启 reranker 的 Hybrid 没有可见提升。
- 3 道“资料不足”题中 2 道被正确拒答；R064（禁用渔药清单）被误答，说明词面 gate 不是语义蕴含判断。
- 所有 gold child chunk 都能在 Qdrant 中找到；49 个 gold parent chunk 按设计不是独立 point，评测按“返回给 LLM 的 parent 上下文”计主指标，并另报 child 精确指标。

## 2. 数据集与索引

| 项 | 值 |
|---|---|
| 题集 | `eval/real_questions_v1.jsonl` |
| 题数 | 65（62 可回答 + 3 资料不足） |
| 标注状态 | `ai_assisted_pending_human_review`，**不是人工确认的 ground truth** |
| 文档 | DB36/T 2225—2026 中华绒螯蟹（9 页，34 child chunks）；DB46 南美白对虾征求意见稿（18 页，109 child chunks） |
| 索引 | `kb_chunks_bge_m3_v1`，5 个 active 文档、155 个 child points |
| Dense | BGE-M3，1024 维，Cosine |
| Sparse | 应用侧 jieba + 自定义词，Qdrant `bm25` sparse，`modifier=IDF` |
| Hybrid | RRF，`rrf_k=60`，dense/BM25 各取 20 |
| Reranker | `BAAI/bge-reranker-v2-m3`，本机 MPS/fp16 |
| 数据集 SHA-256 | `dd94dfd501d8a346f66cafeada94fda2c8c9721ce935b34d364bdbdb6872dc6a` |

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
| Dense | 0.8737 | 0.9140 | 0.8790 | 0.9108 | 0.7957 | 0.8763 | 0.8707 | 0.7715 | 62.2 |
| BM25 | 0.8898 | 0.9355 | 0.8952 | **0.9452** | 0.8610 | 0.8548 | 0.8646 | 0.7941 | 18.5 |
| Hybrid | 0.8844 | 0.9220 | 0.8873 | 0.9252 | **0.8620** | 0.8844 | 0.8873 | **0.8426** | 55.2 |
| Hybrid + Reranker | **0.8898** | **0.9355** | **0.8952** | 0.9347 | 0.8393 | **0.8979** | **0.8957** | 0.8168 | 1036.3 |

说明：

- BM25 与 Hybrid+Reranker 的 parent Recall 相同，但 BM25 的 nDCG@10 更高；reranker 把部分正确证据排在更后面，也把另一些题（如 R024）从第 6–8 位提到第 4 位。
- Hybrid 的 MRR 最高，说明 RRF 在“第一个相关结果”上更稳；其 nDCG@10 低于 BM25。
- Reranker 的 child nDCG/MRR 优于 BM25，但 parent nDCG@10 低于 BM25，且延迟从 18.5 ms 增至 1036.3 ms（约 56×，含本机 MPS 推理）。
- **没有一种模式全面胜出**，不能根据这批数据宣称 reranker 或 hybrid 必然优于 BM25。
- 本表 Dense 有 1 道可回答题（R061，跨 DB36/DB46 的溶解氧对比）因 Query IR 变体证据未覆盖而被 gate 拒答；其余模式在 62 道可回答题上均未拒答。该题按 0 计入 Dense 均值。

## 5. 结果 B：关闭 Query IR 的消融

同题集、同索引，仅关闭 Query IR（纯 Dense/BM25/RRF）。用于区分“检索器本身”和“查询改写”的贡献。

| mode | Recall@5 | Recall@10 | nDCG@5 | nDCG@10 | MRR@10 | 平均耗时 ms |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.8521 | 0.8763 | 0.8610 | 0.8767 | 0.7530 | 53.9 |
| BM25 | 0.8898 | 0.9355 | 0.8952 | 0.9452 | 0.8610 | 17.3 |
| Hybrid | 0.8790 | 0.9167 | 0.8843 | 0.9195 | 0.8257 | 45.7 |
| Hybrid + Reranker | 0.8898 | 0.9355 | 0.8952 | 0.9347 | 0.8393 | 1020.4 |

Query IR 使 Dense 的 Recall@10 从 0.8763 升到 0.9140，Hybrid 从 0.9167 升到 0.9220；BM25 不变（其查询词未被别名扩展改变），reranker 的 parent 指标也不变。该提升幅度只对应这批题和这套规则，不能外推。

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

这些失败没有被“平均分”掩盖；它们指向下一阶段的具体工作：查询词/领域词典、跨文档证据聚合、reranker 候选与排序诊断。

## 7. 可复现实验

```bash
cd apps/api

# 系统默认（Query IR 开）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --query-ir --out ../../eval/runs/real_questions_v1_query_ir

# 消融（Query IR 关）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --out ../../eval/runs/real_questions_v1
```

产物：

- `eval/runs/real_questions_v1_query_ir/{details.jsonl,summary.csv,manifest.json}`
- `eval/runs/real_questions_v1/{details.jsonl,summary.csv,manifest.json}`

`manifest.json` 记录数据 hash、模型、collection、`query_ir` 开关和 git commit；`details.jsonl` 保留逐题排名、gold 排名和拒答原因。

## 8. 限制

1. **只有 2 份真实标准**，155 个 child points；不能代表通用水产养殖语料。
2. **gold 是 AI 辅助构建、待人工复核**，不是人工 qrels；`grade=1/2` 尚未经过第二人校准。
3. 主指标是 parent 级，相对 child 级偏宽；child 指标已同时报告，避免只挑好看的数。
4. 单机单次运行，无置信区间/显著性检验；耗时受 MPS、缓存和并发影响。
5. PDF 表格/页眉切分仍可能造成 gold 证据不完整；R006/R039 的“未命中”可能同时包含索引词和切分因素。
6. 本评测不调用生成模型，不能说明最终答案事实正确；生成质量需另做人工/自动校验。
