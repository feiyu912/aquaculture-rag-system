# 增强架构与实施状态

> 定位：在已跑通的 Hybrid RAG 基线上做**可关闭、可消融**的增强，不把课题改成知识图谱或 Agent 算法研究。
> 正式题目仍为《基于检索增强生成的水产养殖知识问答系统设计与实现》。

## 1. 能力矩阵

| # | 能力 | 当前状态 | 代码/开关 | 说明 |
|---|---|---|---|---|
| 1 | 领域实体识别与归一化 | ✅ 基础 | `species.py`、`query/ir.py`、`graph/service.py` | 品种 + 11 个种子实体/别名；通用实体仍靠人工审核 |
| 2 | Typed Query IR / NL2IR | ✅ 规则 v1 | `query/ir.py` | 意图、品种、阶段、水质指标、年份、规范标记；不调用 LLM |
| 3 | 硬约束过滤 | ✅ 部分 | IR → Qdrant filter | 唯一品种、显式分类可硬过滤；年份/规范状态**不**偷懒编译 |
| 4 | 领域图扩展 | ✅ Phase 2a | `ENABLE_GRAPH_EXPANSION=false` | PostgreSQL 实体/别名/关系/mention；已验证关系的有界多跳扩展（默认 2 跳、可反向）+ Graph-to-Chunk；默认关闭 |
| 5 | 多查询 / 问题分解 | ✅ 规则 v1 | `ENABLE_QUERY_DECOMPOSITION=false` | 按 facet/连接词拆子查询并参与 RRF；子查询继承品种/分类过滤；多跳证据合并仍待做 |
| 6 | Contextual Retrieval | ✅ 可开关 | `ENABLE_CONTEXTUAL_RETRIEVAL`、`ingestion/context.py` | `context_text` 与原文分离；70 题同 qrels 下 Dense/Hybrid 提升、reranker Recall@5 小回退；默认关闭，待人工 qrels |
| 7 | Parent-Child / Neighbor | ✅ 基础 | `ingestion/chunker.py`、`retrieval/service.py` | 已有父块扩展；邻居扩展未单独实现 |
| 8 | 表格感知 | ✅ 基础 | 表格独立父块、表头/单位保留 | 复杂跨页表格仍需 MinerU/人工校验 |
| 9 | 自适应检索路由 | ✅ 确定性 v0 | `ENABLE_ADAPTIVE_ROUTING=false`、`retrieval/service.py` | `calculation`/现行规范在缺工具/日期元数据时安全拒答；LangGraph 未接入 |
| 10 | 去重 / 多样性 | 部分 | parent 聚合、RRF | 没有显式 MMR / section diversity 控制 |
| 11 | 证据完整性 / 补充检索 | ✅ 可开关 | `ENABLE_EVIDENCE_REQUIREMENTS`、`ENABLE_TARGETED_RETRIEVAL` | facet 覆盖检查 + 最多一次定向补检；默认关闭 |
| 12 | 声明级引用验证 | ✅ v0 | `generation/claims.py`、`generation/semantic_claims.py` | 句子级/带引用表格行 `[S1]` + 词面支持性；可选 BGE-M3 余弦筛选；**不是 NLI** |
| 13 | 软删除向量清理 | ✅ 基础 | `maintenance/cleanup.py`、ARQ task、CLI | 删除后 best-effort 异步清理派生 points 并刷新 manifest；DB/原文件保留，归档 retention 未做 |
| 14 | MPS 多进程并发 | ✅ 基础 | `runtime/mps_lock.py` | 同机 `fcntl` 文件锁串行化 MPS 推理；不减少每进程模型内存 |

## 2. 目标链路（Phase 2/3 完成后）

```text
Query
  → Query IR (rules now, optional LLM later)
  → deterministic constraint compiler
  → (optional) entity linking / graph expansion
  → (optional) multi-query / decomposition
  → Dense + BM25 + Graph-to-Chunk
  → RRF / weighted fusion
  → dedup + reranker
  → parent/neighbor expansion
  → evidence sufficiency (+ targeted retry)
  → grounded generation
  → citation validity + claim support
```

当前实际默认链路只包含：

```text
Query IR → species/category hard filter → Dense + BM25 → RRF
→ parent expansion → lexical evidence gate → Mock/DeepSeek
→ citation validity + claim-level lexical check
```

可选模块（默认关闭）：`ENABLE_GRAPH_EXPANSION`、`ENABLE_EVIDENCE_REQUIREMENTS`、
`ENABLE_TARGETED_RETRIEVAL`、`ENABLE_ADAPTIVE_ROUTING`。

## 3. 分阶段实施

### Phase 2a（已完成，默认关闭）

- PostgreSQL 轻量图：`graph_entities` / `graph_aliases` / `graph_relations` / `kb_chunk_entities`。
- 关系带 `review_status`、`confidence`、可选 `provenance_document_version_id`；只加载 `verified` 关系。
- 入库时用最长别名匹配建立 chunk→entity mention；`scripts/seed_graph.py` 可回填旧文档。
- 查询时：实体链接 → 有界多跳关系扩展（默认 `GRAPH_MAX_HOPS=2`，可双向）→ Graph-to-Chunk（按 mention 取 active version 的 child chunk）→ 以 `GRAPH_RRF_WEIGHT` 参与 RRF；trace 记录每跳 `path`/`direction`。
- 没有 `RELATED_TO` 万能关系；没有 Neo4j；没有跨文档推断。
- 当前图来源于人工审核的 11 个种子实体/10 条关系（含 species->水质），不是从论文数据自动抽取的完整领域图。
- 规则问题分解：多指标问题拆成 facet 子查询，子查询保留品种/阶段前缀并继承原问题硬过滤；原问题始终参与召回。图谱多跳扩展已实现路径 trace；跨文档**证据级**多跳推理仍未实现。

### Phase 1（已完成）

- Typed Query IR v1：规则抽取 + 确定性 validator/compiler；原始问题保留。
- 品种/分类硬约束；多品种、年份、规范状态不误编译。
- Contextual Retrieval：`context_text` 入库，索引开关，引用仍用原文。
- 声明级引用检查 v0：`[S1]` 映射、状态、summary 持久化。
- 检索 Trace：`GET /api/debug/query-logs/{request_id}`。
- 回归：114 个默认单元测试（另 2 个真实 BGE 集成测试）、A/B/C smoke、四模式评测；图和补检默认关闭。

### Phase 2b（下一步）

1. PostgreSQL 轻量图：
   - `domain_entities` / `domain_aliases` / `domain_relations` / `entity_mentions`；
   - 关系必须带 `provenance_document_version_id`、`review_status`、`confidence`；
   - 只允许白名单关系类型，不用万能 `RELATED_TO`。
2. 实体链接：品种 + 水质指标 + 疾病/症状 + 阶段；未审核关系不得生成确定性结论。
3. Graph-to-Chunk：通过 mention 找 chunk，再进入 RRF；保留命中路径。
4. 多查询/问题分解：子查询继承原问题的品种/时间/规范硬约束；原查询始终保留。
5. Evidence requirements + targeted re-retrieval：按 facet 检查缺口，最多补检 `MAX_TARGETED_RETRIEVAL` 次。
6. 消融开关：`ENABLE_GRAPH_EXPANSION`、`ENABLE_QUERY_DECOMPOSITION`、`ENABLE_TARGETED_RETRIEVAL`。

### Phase 3（工程收尾）

- LangGraph 编排 `SIMPLE / SEMANTIC_EXPANSION / MULTI_HOP / REGULATION / CALCULATION`；限制重试、超时、token 预算。
- PDF.js 页码 + bbox 高亮；Next.js 前端。
- 200 条人工评测集；Recall@K、nDCG@K、MRR、引用支持率、正确拒答/错误拒答、P50/P95、token 成本。
- 与陶江老师确认数据来源与品种范围后再扩充品种；不预先收集几十个品种。

## 4. 论文口径边界

可以写：

- 规则/LLM 辅助的 Query IR 与确定性约束编译；
- 版本化 Parent-Child 索引与可追溯引用；
- Contextual Retrieval 的开关消融；
- 引用有效性、词面支持性、事实正确性的分层，以及当前 v0 的局限；
- 四模式检索消融与证据不足拒答。

**不能写**（当前未实现）：

- 已完成 GraphRAG / Neo4j 图数据库；
- 已完成多跳 Agent 或 LangGraph 自适应路由；
- 声明级支持性等于事实正确性；
- 把 `noop` 消融结果写成 BGE 重排结果；BGE-Reranker 已接入，但收益仍需 qrels 验证；
- 已在真实水产数据上验证图扩展/Contextual 的收益。

## 5. 数据与安全约束

- LLM 抽取的实体/关系必须绑定来源版本并经过审核；未审核关系只能做候选召回，不能直接生成用药/诊断结论。
- 品种过滤是文档级；混排文档必须拆档。
- bbox 不发送给 DeepSeek；页码/原文是可接受的降级定位。
- API Key 只从环境变量读取，不写入日志或仓库。
