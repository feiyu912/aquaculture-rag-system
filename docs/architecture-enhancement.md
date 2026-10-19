# 增强架构与实施状态

> 定位：在已跑通的 Hybrid RAG 基线上做**可关闭、可消融**的增强，不把课题改成知识图谱或 Agent 算法研究。
> 正式题目仍为《基于检索增强生成的水产养殖知识问答系统设计与实现》。

## 1. 能力矩阵

| # | 能力 | 当前状态 | 代码/开关 | 说明 |
|---|---|---|---|---|
| 1 | 领域实体识别与归一化 | 部分 | `species.py`、`query/ir.py` | 品种已归一化；通用实体表/别名表待 Phase 2 |
| 2 | Typed Query IR / NL2IR | ✅ 规则 v1 | `query/ir.py` | 意图、品种、阶段、水质指标、年份、规范标记；不调用 LLM |
| 3 | 硬约束过滤 | ✅ 部分 | IR → Qdrant filter | 唯一品种、显式分类可硬过滤；年份/规范状态**不**偷懒编译 |
| 4 | 领域图扩展 | ⏳ Phase 2 | `ENABLE_GRAPH_EXPANSION=false` | 表结构、实体/关系/来源/审核、Graph-to-Chunk 尚未实现 |
| 5 | 多跳 / 问题分解 | ⏳ Phase 2 | `strategy=multi_hop` 仅标记 | 尚未真正拆子问题、合并证据 |
| 6 | Contextual Retrieval | ✅ 可开关 | `ENABLE_CONTEXTUAL_RETRIEVAL`、`ingestion/context.py` | `context_text` 与原文分离；默认关闭 |
| 7 | Parent-Child / Neighbor | ✅ 基础 | `ingestion/chunker.py`、`retrieval/service.py` | 已有父块扩展；邻居扩展未单独实现 |
| 8 | 表格感知 | ✅ 基础 | 表格独立父块、表头/单位保留 | 复杂跨页表格仍需 MinerU/人工校验 |
| 9 | 自适应检索路由 | ⏳ Phase 3 | `query/ir.py:route_query` | 已有确定性 route 函数；LangGraph 未接入 |
| 10 | 去重 / 多样性 | 部分 | parent 聚合、RRF | 没有显式 MMR / section diversity 控制 |
| 11 | 证据完整性 / 补充检索 | 部分 | `retrieval/sufficiency.py` | 有词面 gate 与 missing_terms；定向补检未实现 |
| 12 | 声明级引用验证 | ✅ v0 | `generation/claims.py` | 句子级 `[S1]` 映射 + 词面支持性；**不是 NLI** |

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

## 3. 分阶段实施

### Phase 1（已完成）

- Typed Query IR v1：规则抽取 + 确定性 validator/compiler；原始问题保留。
- 品种/分类硬约束；多品种、年份、规范状态不误编译。
- Contextual Retrieval：`context_text` 入库，索引开关，引用仍用原文。
- 声明级引用检查 v0：`[S1]` 映射、状态、summary 持久化。
- 检索 Trace：`GET /api/debug/query-logs/{request_id}`。
- 回归：52 个单元测试、A/B/C smoke、四模式评测。

### Phase 2（下一步）

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
- `hybrid_rerank` 已经是 BGE 重排（当前默认 `noop`）；
- 已在真实水产数据上验证图扩展/Contextual 的收益。

## 5. 数据与安全约束

- LLM 抽取的实体/关系必须绑定来源版本并经过审核；未审核关系只能做候选召回，不能直接生成用药/诊断结论。
- 品种过滤是文档级；混排文档必须拆档。
- bbox 不发送给 DeepSeek；页码/原文是可接受的降级定位。
- API Key 只从环境变量读取，不写入日志或仓库。
