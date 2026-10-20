# 真实模型接入与验证记录（2026-10-20）

> 本文只记录**实际执行过**的安装、加载、检索和测试结果。
> 未配置 key 的生成服务明确标记为“未验证”，不把 Mock 结果写成 DeepSeek/其他模型结果。
> 架构审计快照见 [audit-2026-10-20.md](audit-2026-10-20.md)，其中 Hash/noop 的判断已被本文替代。

## 1. 环境

| 项 | 实际值 |
|---|---|
| 机器 | Apple M5，32 GB RAM，macOS |
| Python | 3.13.14（uv 管理） |
| PyTorch | 2.14.1，MPS 可用 |
| Transformers | 5.20.2 |
| FlagEmbedding | 1.4.2（`uv sync --extra bge` 安装） |
| BGE-M3 | `BAAI/bge-m3`，HF revision `5617a9f61b028005a4858fdac845db406aefb181` |
| BGE-Reranker | `BAAI/bge-reranker-v2-m3`，本地目录 `models/bge-reranker-v2-m3`，权重 `sha256` 前缀 `d9e3e081faff1eefb84019509b2f5558` |
| 运行设备 | MPS，fp16 开启 |
| 生成 | OpenAI 兼容网关，`openai-compatible-model` |
| Qdrant | server 1.12.4，client 1.12.1 |

安装命令：

```bash
cd apps/api
uv sync --extra bge
```

模型缓存完成后，API/worker 使用离线模式，避免运行期访问 Hugging Face 元数据超时：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 2. 索引迁移

- 旧开发集合：`kb_chunks_dev_v1`（Hashing 向量，保留，不删除）。
- 新集合：`kb_chunks_bge_m3_v1`，独立创建，未覆盖旧集合。
- 重建命令：

```bash
cd apps/api
uv run python ../../scripts/reindex_collection.py \
  --collection kb_chunks_bge_m3_v1 \
  --embedding-model BAAI/bge-m3 --batch-size 8
```

首次重建（3 个示例文档、4 个版本）结果：12 points，耗时 7.9 s。

真实 PDF 入库后：

| 指标 | 值 |
|---|---|
| 文档数（active） | 5 |
| 版本数（含 archived） | 6 |
| Qdrant points | 190 |
| manifest collection | `kb_chunks_bge_m3_v1` |
| manifest embedding | `BAAI/bge-m3` |
| manifest vector size | 1024 |
| manifest chunk hash | `4868e31c4d1aa57cb93f7a7f266f57f42a7ba1b377b864be70c1641e62c896e0` |
| `check_index.py` | `ok=true`，无 orphan version，无 warning |

一致性行为：

1. `index_manifests` 记录 collection、embedding model、vector size、chunk config hash、文档数、点数、状态。
2. 查询前读取 manifest；collection 与配置不一致或 manifest 缺失且 `INDEX_MANIFEST_REQUIRED=true` 时返回 `index_manifest_mismatch`，不混检。
3. 一个文档版本可以同时存在于旧 Hash 集合和新 BGE 集合；查询时以**当前 collection 的 manifest** 为准，版本元数据只作为没有 manifest 时的回退。
4. 每次激活新版本后刷新 manifest 的 document/point count；`check_index.py` 会把 manifest 点数与 Qdrant 实际点数对账。

## 3. 真实模型实测

### 3.1 BGE-M3

| 检查 | 结果 |
|---|---|
| 输出维度 | 1024 |
| L2 范数 | 1.0（归一化） |
| 首次加载 | 5.9 s（fp16=false）/ 3.2 s（fp16=true，权重已缓存） |
| 2 条文本编码 | 1.66 s（fp32）/ 0.58 s（fp16） |
| API 首次请求 | 10.4 s（包含模型加载，不计入稳态） |
| API 稳态检索 | 约 94 ms Dense，整体约 0.4 s（Mock 生成） |

真实模型集成测试：

```bash
cd apps/api
RUN_BGE_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest tests/test_bge_integration.py -q
# 2 passed in 10.18s
```

### 3.2 BGE-Reranker

3 条候选的独立加载测试：

```text
query: 中华绒螯蟹对溶解氧有什么要求？
relevant  溶解氧宜保持在 5 mg/L 以上。       score 0.5148
irrelevant 今天上海天气晴朗。                score 0.000016
other     氨氮宜控制在 0.2 mg/L 以下。       score 0.0093
```

排序正确；模型加载 3.7 s，首次 3 条打分约 4.0 s（含 MPS 预热）。

API 真实 `hybrid_rerank` trace：

```text
retrieval_mode = hybrid_rerank
reranker       = BAAI/bge-reranker-v2-m3
embedding      = BAAI/bge-m3
manifest point_count = 190
```

实测延迟（同一台机器，190 points）：

| 场景 | retrieval_ms | 说明 |
|---|---:|---|
| 首次 rerank 请求 | 4070.6 | 包含 reranker 首次加载/预热，不计入稳态 |
| 第二次 rerank 请求 | 2669.4 | 8 个候选、MPS、fp16；当前实现串行 compute_score |
| 非 rerank `hybrid` 稳态 | 94–124 | BGE-M3 Dense + BM25 + RRF |

`hybrid_rerank` 的 trace 现在明确记录真实模型；`noop` 只作为消融对照，不能再把 noop 结果称为 BGE 重排。

### 3.3 BM25

- collection 的稀疏向量配置：`bm25: {"modifier": "idf"}`。
- 文档向量只包含 BM25 词频饱和项；查询向量词项权重固定为 1.0；IDF 由 Qdrant 服务端加一次。
- 实测：`溶解氧 溶解氧 氨氮` 的文档向量只有两个唯一 index；`query_vector` 所有值为 1.0；重复词项不会生成重复 index。
- 未发现“应用侧再乘 IDF”的重复计算；`avg_len` 仍是固定配置（300），这是近似，不是按集合统计的动态平均长度。
- 测试：`tests/test_bm25.py` 覆盖领域词、唯一 index、查询单位权重、文档权重不乘 IDF。

## 4. 真实 PDF 数据

已下载并入库三份公开地方标准（文件在 gitignored 的 `data/real/`）：

| 文档 | 来源 | 页数 | child chunks | 入库结果 |
|---|---|---:|---:|---|
| DB36/T 2225—2026 中华绒螯蟹池塘培育扣蟹技术规程 | [江西省地方标准公开下载](https://dbba.sacinfo.org.cn/portal/download/19dca81b5f6a3527edbeeb8751ef481761179f54b87450a826f58e9482824cbb) | 9 | 34 | succeeded |
| DB46 农产品全产业链生产规范 南美白对虾（凡纳滨对虾） | [海南省地方标准公开征求意见稿](https://amr.hainan.gov.cn/hd/zjdc/202512/P020251215594992940559.pdf) | 18 | 109 | succeeded |
| DB32/T 5292—2025 中华绒螯蟹生态育苗技术规范 | [江苏省地方标准公开下载](https://dbba.sacinfo.org.cn/portal/download/e8bf2eb07f3029819fc92b236df076cfd189630884e207fe2c62668353227eb5) | 7 | 35 | succeeded |

三份文件于 2026-10-20 下载；DB46 标注为“征求意见稿”，论文引用时需注明版本状态，不能当作正式发布标准；DB32 为 2025-12-30 发布、2026-01-30 实施的正式地方标准。

查询验证：

- “中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？”返回 DB36 标准第 5、7 页和示例资料；DB36 第 7 页直接含“溶氧量 5 mg/L 以上”。
- “凡纳滨对虾养殖水质的酸碱度要求是什么？”返回 DB46 标准第 5、6、16 页与示例资料；引用页码与版本映射可用。
- 这三份文档是真实公开标准，但不是人工标注 qrels；当前 6 个 active 文档（另含 1 份示例/合成资料）仍不足以报告检索效果。

## 5. 生成服务

当前 `.env` 已配置用户提供的 OpenAI 兼容网关（key 不写入仓库、不打印）：

```text
LLM_PROVIDER=openai_compatible
OPENAI_BASE_URL=https://gateway.example.com/v1
OPENAI_MODEL=openai-compatible-model
```

网关没有实现 `GET /models`（返回 404），但 `POST /chat/completions` 实际返回 200：

```json
{"ok": true, "generation_status": 200, "finish_reason": "stop",
 "content": "连通", "usage": {"prompt_tokens": 38, "completion_tokens": 163}}
```

检查命令：

```bash
cd apps/api
uv run python ../../scripts/check_llm.py --generate
```

真实 API/SSE 验证：

- `GET /api/health`：`llm_provider=openai_compatible`，`llm_configured=true`。
- 问题“中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？”，`hybrid_rerank`：
  - trace `llm_model=openai-compatible-model`；
  - 回答引用 DB36 标准第 7 页“溶氧量 5 mg/L 以上”；
  - 引用有效，coverage 0.625（词面覆盖率，不是事实正确率）；
  - total 10.85 s，retrieval 3.10 s，generation 3.78 s。
- A/B/C smoke（真实 BGE + 真实外部生成）全部通过：
  `PASS ingest / four retrieval modes + species filter / citation source resolves to PDF /
  version update activates v2 / rollback / insufficient-evidence refusal`。

重要观察：

- 同一问题在 `hybrid` 下没有把 DB36 第 7 页的 8.1 水质指标排进最终 5 条证据，外部模型因此回答“没有具体数值”；
- `hybrid_rerank` 把该页排入并列出了 `5 mg/L 以上`，这是当前 BGE reranker 产生正向收益的一个具体样例，但只是单例，不能替代 qrels 统计。

原生 DeepSeek endpoint 未配置 key，因此 **DeepSeek 原生调用未验证**；已验证的是 OpenAI 兼容网关。缺少 key 时 `build_generator` 抛 `LLMError`，API 返回 503，不会静默回退 Mock；模型返回空可见文本时也会发 `empty_generation` 错误。

## 6. 测试与静态检查

```bash
cd apps/api
uv run pytest -q
# 113 passed, 2 skipped（BGE 集成测试默认跳过）
uv run ruff check app tests ../../scripts
```

开启真实模型集成测试：

```bash
RUN_BGE_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest tests/test_bge_integration.py -q
# 2 passed
```

## 7. 已验证 / 未验证

**已验证**

- BGE-M3 真实加载、1024 维归一化输出、MPS/fp16。
- BGE-Reranker 真实加载、相关性排序、API `hybrid_rerank` trace。
- 独立 collection 重建、manifest、查询期守卫、点数对账。
- BM25 分词/权重与 Qdrant IDF 配置。
- 三份真实地方标准的上传、解析、版本、页码引用、Qdrant 检索。
- 软删除后的异步向量清理：真实上传 1 页测试文档（1 个 point），`DELETE` 返回 204，worker 将其 points 从 1 清到 0，manifest 保持 6 文档/190 points。
- 同机 MPS 文件锁：BGE-M3 在锁内完成真实 1024 维推理；锁路径 `/tmp/aquaculture_rag_mps.lock`。
- 可选 `ENABLE_SEMANTIC_CLAIMS=true` 的 BGE-M3 余弦 claim 筛选：真实 SSE 下 `claim_summary.support_rate=0.8`，一条词面 unverified 的说明句被余弦升级；但这只是相似度，不是 NLI。
- 113 个默认测试通过；2 个真实 BGE 集成测试通过。

**未验证 / 不足**

- DeepSeek 原生 endpoint（未配置其 key）；已验证的是用户提供的 OpenAI 兼容网关。
- 人工 qrels；当前 70 条真实题仍为 AI 辅助标注、待人工复核。
- BGE-Reranker 收益是否稳定超过 RRF；当前只有单机延迟和少量样例。
- PDF.js bbox 高亮；当前只有页码跳转和 bbox 数据。
- MinerU 对扫描件/表格/双栏的收益。
- Contextual Retrieval 在真实数据上的收益：已做两条 query 的小样本检查，结果混合/偏负，尚不能做同 qrels 消融。
- 多进程 MPS 的内存占用未压测；文件锁只串行推理，不减少每个进程各自的模型内存。
- 旧版本/归档版本的保留策略与自动 retention 仍未实现（当前只清理软删除文档的派生向量）。

### 软删除异步清理与 MPS 锁 smoke

软删除链路：

1. 上传 1 页、1 个 child chunk 的临时 PDF，Qdrant 该版本点数 = 1。
2. `DELETE /api/documents/{id}` 返回 204，DB 行与原始 PDF 保留，版本归档。
3. API best-effort 入队 `cleanup_deleted_vectors`；worker 调用 `purge_deleted_vectors(apply=True)`，该版本点数变为 0。
4. worker 刷新 manifest，active 文档/点数仍为 6/190，没有误删 active 文档。

MPS 锁：

- `BGEM3Embedder`/`BGEReranker` 原先只有线程锁；多个 uvicorn/ARQ 进程仍可能同时提交 Metal 工作。
- 新增 `app/runtime/mps_lock.py`，在 `device=mps` 且 `MPS_LOCK_ENABLED=true` 时用 `fcntl.flock` 跨进程串行化推理。
- 新增测试覆盖锁创建、线程串行化、异常透传、禁用时 no-op；真实 BGE-M3 在锁内完成一次 1024 维 embed。
- **限制**：锁不减少内存；每个进程仍各有一份模型。生产部署仍建议 API/worker 各一个进程，或把推理集中到专用服务。

## 8. 下一步

1. 已完成 OpenAI 兼容网关的 `check_llm.py --generate` 与真实 SSE；下一步补 DeepSeek 原生 endpoint 的可选验证（不是当前阻塞项）。
2. 扩充真实文献到至少 20–50 份，建立人工 qrels，分别评 Dense/BM25/Hybrid/+Reranker。
3. 测量 reranker 候选数（8/16/20）与 P50/P95、nDCG，决定默认候选数。
4. `kb_chunks_bge_m3_ctx_v1` 已重建为 6 文档/190 points；下一步修正脏 heading 后做同 qrels 消融。
5. 接 PDF.js bbox 高亮；再评估 MinerU。

## LLM-Assisted NL2IR / Query Planner（真实模型）

实现位置：`apps/api/app/query/planner.py`；开关 `ENABLE_LLM_PLANNER=true`，默认关闭。  
模型：已验证的 OpenAI 兼容网关 `openai-compatible-model`，非 Mock。  
调用方式：非流式 `POST /chat/completions`，`response_format={"type":"json_object"}`；返回内容再做 Pydantic 严格校验。

### 已验证的安全边界

- LLM 只输出 `PlannerIR`（intent / species / growth_stage / water_parameters / diseases / constraints / assumptions / rewritten_query / subquestions / confidence / warnings）。
- `source=inferred` 的物种不会进入 Qdrant 硬过滤；只有用户问题中明确出现、且唯一匹配已知品种的 species 才能成为 `species_filter`。
- 规则 IR 已产生的硬过滤优先于 LLM；LLM 不能放宽已有的 `species_filter`/`category_filter`。
- planner 对不存在的品种、非领域 facet、未在问题中出现的 water/stage/disease 做丢弃并记录 warning。
- planner JSON 解析/校验失败时**安全回退规则 IR**；网络错误不重试，解析失败最多重试 1 次（token 预算增加）。
- `trace.llm_planner` 只记录结构化计划、耗时、attempts、错误，不记录密钥或完整原始响应。

### 5 题规则 vs LLM 规划对照

人工确认的规划标签（品种硬过滤、水质指标、阶段、intent）；不是检索相关性标签。

```text
cd apps/api
.venv/bin/python ../../scripts/compare_query_planners.py --mode both \
  --out reports/query-planner-comparison.json
```

结果（2026-10-20）：

| planner | species_ok | water_recall | water_precision | stage_recall | intent_ok |
|---|---:|---:|---:|---:|---:|
| rule IR | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| LLM planner | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

- 5 题全部一致（disagreements=0，llm_errors=0）。
- **这是 ceiling effect**：样例都是规则已能处理的简单/中等问题；不能据此宣称 LLM 规划更优，也不能外推到 50+ 题或复杂多跳。
- LLM 单题规划约 20–40 s（reasoning token 占预算），明显慢于规则 IR；默认关闭是刻意的。
- 详细逐题结果：[query-planner-comparison.json](../apps/api/reports/query-planner-comparison.json)。

## 真实检索评测（70 题）

数据集、指标定义、失败分析和复现命令见 [retrieval-evaluation-2026-10-20.md](retrieval-evaluation-2026-10-20.md)。

语料已扩充到 3 份真实标准（DB36、DB46、DB32），`kb_chunks_bge_m3_v1` 现为 **6 个 active 文档 / 190 个 child points**；题集 70 题（67 可回答 + 3 资料不足），标注仍为 AI 辅助待人工复核。

系统默认（Query IR 开）的主结果：

| mode | Recall@10 | nDCG@10 | MRR@10 | 平均耗时 ms |
|---|---:|---:|---:|---:|
| Dense | 0.8781 | 0.8863 | 0.7736 | 69.5 |
| BM25 | 0.9279 | 0.9328 | 0.8113 | 18.1 |
| Hybrid | 0.8831 | 0.8881 | 0.8226 | 55.0 |
| Hybrid + Reranker | **0.9353** | **0.9354** | **0.8488** | 1043.8 |

- 67 道可回答题的整体指标；3 道资料不足题单独统计，2/3 被正确拒答。
- 本版 reranker 的 parent/child 指标均最高，但 BM25 的 nDCG@10 仅低 0.0026，且耗时约为 reranker 的 1/58；不能据此宣称 reranker 在任意语料上更优。
- 上一版两文档语料中 BM25 的 nDCG@10 最高，加入 DB32 干扰项后排序变化，说明结果对语料/候选池敏感。
- 所有 56 个唯一 gold child chunk 均存在于 Qdrant；gold parent chunk 按设计不是独立 point，主指标按返回的 parent 上下文计，另报 child 精确指标。
- 局限：3 份真实标准、190 个 child points，AI 辅助待人工复核，无置信区间；不能据此宣称通用优越性。

### Contextual Retrieval 小样本检查（非基准）

`kb_chunks_bge_m3_ctx_v1` 已按同一批 6 个 active 文档重建（190 points，`contextual=true`），但只做了两条查询的 smoke，不是同 qrels 消融：

- “扣蟹培育的水质指标有哪些？”：四模式都能把 DB36 第 7 页“8.1 水质指标”排进结果，gate 判充分。
- “DB32/T 5292—2025 生态育苗的水温和pH适宜范围是多少？”（修复前）：Dense 的 top1 是第 5 页“4.3 水质要求（盐度）”，BM25 的 top1/top2 是封面和目次，Hybrid/Reranker 的 top1 是第 4 页术语；真正的第 6 页“6.4 水质控制（水温 18~21 ℃、pH 6.5~8.5）”没有排到第 1。gate 仍判充分，说明**检索到相关词不等于检索到答案证据**。
- 已定位并修复一个直接噪声源：`100 mg/L 的漂白粉...` 这类 55 字符句子被 `HEADING_RE` 当成章节标题，进入 `context_text`。修复包括 parser 数字标题规则、`sanitize_heading_path`、以及 [repair_context.py](scripts/repair_context.py) 对现有 123 个 chunk 的 metadata 修复（不改 chunk ID/content/ordinal）。
- 修复后重建 ctx collection 再测：Dense 的 top1 仍是第 5 页“4.3 水质要求”，但第 6 页“6.4 水质控制”升到**第 2**；Hybrid/Reranker 的 top1 是第 4 页术语，第 6 页也在第 2；BM25 仍是封面/目次。没有变成 top1，不能声称 contextual 收益。
- 结论：Contextual Retrieval 继续默认关闭；heading 噪声已降低，但“盐度 4.3”与“水温/pH 6.4”的同章节语义竞争仍在。下一步需做 70 题同 qrels 消融，而不是只修一个 heading。

### 图谱多跳 smoke

`expand_entities("浮头怎么办？", max_hops=2, bidirectional=True)` 在人工审核的 11 实体/8 关系图上返回：

`浮头 -> 溶解氧 -> 水质`（2 跳）与 `浮头 -> 溶解氧 -> 增氧`（反向 2 跳），每条 trace 都带 `path`、`direction`、`hop`。这证明多跳遍历和 provenance 代码路径可用。

但把 `GRAPH_EXPANSION=true` 用于真实检索时，该 query 没有返回证据 chunk；当前图关系主要来自示例/合成资料的 mention，尚未覆盖 DB36/DB46/DB32 的足够实体。不能据此声称图谱提升了真实问答效果，只能声称“机制和 trace 已验证”。

### DB32 SSE 真模型 smoke

默认 `hybrid_rerank` 对“DB32/T 5292—2025 生态育苗的水温和pH适宜范围是多少？”的 SSE 结果：

- `sources[0]` 是 DB32 第 6 页 `6.4 水质控制`，quote 含“适宜水温为18 ℃~21 ℃。适宜pH为6.5~8.5”；答案给出 18~21 ℃、6.5~8.5，并引用 `[S1]`。
- `citation_check.valid=true`，`cited_indices=[1,5]`，`coverage=1.0`；第一次 smoke 时 Markdown 表格行没有被抽取成 claim，`support_rate=0.167`。已修复 `split_claims` 对带 `[S1]` 的表格数据行的抽取，并加单元测试。
- 词面模式重跑：`support_rate=0.5`（3 supported / 1 weak / 1 uncited / 1 unverified）；“水温 18~21 ℃ [S1]”“pH 6.5~8.5 [S1]”等表格/列表行被正确检查。
- 语义模式（`ENABLE_SEMANTIC_CLAIMS=true`）重跑：`support_rate=0.8`（4 supported / 1 uncited），一条词面 unverified 的“另一标准 pH 7.5~8.5”说明句被 BGE-M3 余弦分数 0.662 升级为 supported。这条句子确实与 S5 有关，但“另一标准/不适用”的对比关系不是余弦相似度能验证的，说明语义筛选会**过度支持**。
- 方法仍是 `lexical_overlap_v0` 或可选 `bge_m3_cosine_v0`；`coverage`/`support_rate` 不是事实正确率，也不是 NLI。

### 尚未解决

- planner 尚未与首轮 dense/BM25 检索并行执行；开启后总延迟会增加一次规划耗时。
- 硬约束 trace 已区分 `document_filter` / `retrieval_requirement` / `soft_context`，但真正作用于 Qdrant 的仍只有文档 species/category。
- 复杂多跳、法规年份、否定/排除条件仍可能被 planner 误判；当前只做保守降级，不做自动事实确认。
