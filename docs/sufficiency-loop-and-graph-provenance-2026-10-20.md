# 证据充分性 targeted loop 与 Graph provenance（2026-10-20）

> 目标：gate 判“证据不足”时，按缺口定向补检索，并用同一 gate 复判；图谱召回要能说清
> “这条证据是经由哪个实体、哪条边、哪个文档版本来的”。阈值不变。

## 1. Targeted loop：从“一条稀释查询”到“每个 requirement 一条查询”

旧实现（`ENABLE_TARGETED_RETRIEVAL=false` 默认关闭）只有一次重试：把**所有**缺失词拼进
一条 `supplement` 查询，且只有当第二次检索自身 `sufficient` 时才合并。问题：

1. 一条查询里塞 3 个 facet，BM25/dense 会被拉向“提到任意一个词”的文档，反而更难覆盖；
2. 第二次必须整体 sufficient 才合并，丢掉“第一次补到盐度、第二次补到 pH”这种增量覆盖；
3. 无法解释补了什么、补到没有。

新实现（`app/retrieval/requirements.py: build_targeted_queries` +
`app/retrieval/service.py`）：

- 每个**未覆盖**的 evidence requirement 生成一条 facet 查询（只含缺失词，如 `总碱度`）：
  把缺失词追加在原问题后面几乎不改变排序，重试会拿回同一批 top-k；facet 查询才能
  把真正写了该指标的段落捞出来。合并后仍用原问题+同一 gate 复判；
- 没有结构化 requirement 时，才退回 gate 的 `missing_terms`（`question + 领域缺失词`）；
- 最多 `MAX_TARGETED_RETRIEVAL=2` 条，按 requirement 去重；
- 每条补检索的结果都合并进候选，然后**重新跑同一个 gate**（`evidence_min_terms=2`、
  `min_weight=3.0`、`min_coverage=0.3` 未改）；仍不足则最终 `sources=[]`；
- `no_query_terms` / `no_evidence` / `current_regulation_unverified` 不重试（重试不可能
  补出证据，只会白增延迟）；
- 只在最外层 `_attempt == 0` 编排，递归调用不会嵌套出 2×2 次检索；
- 响应新增 `targeted_retrieval` trace：

```json
{
  "mode": "requirement_targeted",
  "insufficient_reason": "missing_requirements",
  "targets": [
    {"requirement": "water:0", "label": "水质指标", "terms": ["盐度"],
     "supplement": "… 盐度", "second_sufficient": true,
     "second_gate_reason": "matched", "added_sources": 2}
  ],
  "sufficient_before": false,
  "sufficient_after": true
}
```

默认值：`ENABLE_TARGETED_RETRIEVAL=true`、`MAX_TARGETED_RETRIEVAL=2`；
`ENABLE_EVIDENCE_REQUIREMENTS` 仍默认 false（结构化 requirement 是更严格的档位，
开启后 target 才会按 facet 拆分）。

## 2. Graph provenance：边级来源 + chunk 级路径

### 2.1 边级 provenance

`GraphRelation` 本来就有 `provenance_document_version_id` 和 `confidence`，但
`load_graph()` 丢掉了它们，trace 只剩 source/target/relation_type。现在：

- `RelationData` 增加 `provenance_version_id`、`confidence`；
- `expand_entities()` 的每条 `relation_trace` 增加
  `provenance_version_id`、`confidence`，反向边同样携带；
- 前端/论文可以直接回答“这条 浮头→溶解氧 的边是哪份文件、置信度多少”。

### 2.2 chunk 级 provenance

`graph_chunk_ids()` 只返回 chunk id，图谱命中和普通向量命中在 trace 里无法区分。
新增 `graph_chunk_matches()`（`graph_chunk_ids` 变为薄封装）：

- 返回 `{chunk_id, entity_ids, mention_count}`；
- `retrieval/service.py` 用 expansion 的 `relation_trace.path_entity_ids` 还原每个
  entity 的到达路径，写入 source 的 `graph_provenance`：

```json
{
  "matched_entities": ["溶解氧"],
  "paths": [["浮头", "溶解氧"]],
  "mention_count": 2,
  "seed_terms": ["浮头"]
}
```

- 只有图谱命中的 source 非空，普通向量命中为 `null`；
- `rankings.graph` 仍是 chunk id 列表，保持既有字段不变。

## 3. 真实命令与结果

### 3.1 requirements 档位下的真实触发（cwd `apps/api`）

进程内 `ENABLE_EVIDENCE_REQUIREMENTS=true`、`ENABLE_TARGETED_RETRIEVAL=true`，
其余与默认一致：

```text
Q: 扣蟹培育池的水温和氨氮如何控制？      sufficient=True  reason=matched          （别名修复后首轮即覆盖）
Q: 对虾育苗池的盐度和总碱度要求是什么？    sufficient=False reason=missing_requirements sources=0
   targeted: {"mode":"requirement_targeted","targets":[{"requirement":"water:1",
     "terms":["总碱度"],"supplement":"总碱度","second_sufficient":false,
     "second_gate_reason":"missing_requirements","added_sources":4}],
     "sufficient_before":false,"sufficient_after":false}
Q: 中华绒螯蟹养殖水体的溶解氧和硫化氢如何控制？ sufficient=False reason=missing_requirements
   targeted: {"targets":[{"requirement":"water:1","terms":["硫化氢"],
     "supplement":"硫化氢","added_sources":0}],"sufficient_after":false}
```

解释：

- 补检索确实新增了候选（`added_sources=4`），但本语料没有“总碱度/硫化氢”的正文，
  合并后仍不满足 requirement → 继续拒答、`sources=[]`。**阈值没有被放宽**。
- 同一轮里 `扣蟹培育池` 曾因 `stage:0=扣蟹培育` 被判 missing；把 `扣蟹`/`培育扣蟹`
  纳入 stage 别名后首轮即 `matched`。这是词面覆盖问题，不是 gate 阈值问题。
- 本题库的水质参数高度集中（DB36 8.1、DB32 5.4 一段写全），所以“按 facet 拆分”
  在 70 题里很少触发；loop 的常态收益是 trace 可解释 + 拒答不降阈值。

### 3.2 targeted 合并的关键修复（单测）

真实调试暴露出两个会“白补”的 bug，均已修：

1. 递归 `retrieve` 在 gate 不足时清空 `evidence`，外层拿不到补检索的候选 →
   增加内部参数 `keep_insufficient_evidence=True`，只由 targeted 循环使用；
2. `requirements.covered` 在合并后没有重算，gate 读到的还是旧 flag →
   合并后重新 `assess_requirements`；
3. 合并池大于可见槽位时，覆盖缺失 facet 的 chunk 可能被截掉 →
   `_covering_first()` 把它放进可见槽位，保证 `sufficient_after=true` 时答案引得到。

`tests/test_targeted_retrieval.py` 覆盖：facet 查询构造、去重/上限、gate 词回退、
非领域词不重试、`_covering_first` 的排序与空操作、标题/别名覆盖。

### 3.3 Graph provenance 真实输出

```text
Q: 河蟹池塘出现浮头说明什么？应该怎么增氧？
sufficient True reason matched sources 10
seeds ['增氧', '浮头', '中华绒螯蟹']
expanded ['亚硝酸盐', '凡纳滨对虾', '氨氮', '水温', '水质', '溶解氧', '盐度', '酸碱度'] edges 8
edge: 增氧 -> 溶解氧 MANAGEMENT_FOR hop 1 prov None conf 1.0
edge: 中华绒螯蟹 -> 水质 SPECIES_HABITAT hop 1 prov None conf 1.0
edge: 水质 -> 氨氮 INDICATOR_OF hop 2 prov None conf 1.0
sources with graph provenance: 6
  S2 ['增氧', '氨氮', '溶解氧'] path ['增氧'] mentions 2
  S3 ['增氧'] path ['增氧'] mentions 4
  S7 ['水质'] path ['中华绒螯蟹', '水质'] mentions 3
```

- 10 条 source 里 6 条带 `graph_provenance`，能说清“哪个实体、哪条路径、命中几次”；
- 边级 `provenance_version_id` 目前是 `None`：这 10 条边是 `scripts/seed_graph.py`
  人工维护的领域边，不是从某份 PDF 抽取的。字段与 trace 已就绪，抽取边写入
  `graph_relations.provenance_document_version_id` 后会自动带出，不能把 `None`
  误读成“无来源”。

## 4. 边界

- targeted loop 只在 gate 已经判不足时运行；它可能把“原本会拒答”的问题救回来，但
  不会让原本 sufficient 的结果变差（合并后仍用同一 gate 复判）。
- requirement 拆分依赖 Query IR 的水质/疾病/阶段字段；IR 没抽出的 facet 不会成为
  requirement，也就不会定向补检索。
- 图谱 provenance 只覆盖 `review_status=verified` 的边；未审核边不会进入 trace。
- `relation_trace` 里的 `confidence` 来自抽取阶段，不是校准后的概率，不能当论文的
  统计置信度使用。