# LLM-Assisted Query Planner：实现与验收（2026-10-20）

> 目标：把自然语言问题变成**有类型、可校验、可回退**的 Query IR 和检索任务；LLM 只负责提出计划，不能直接把推断变成硬过滤。
> 默认开关：`ENABLE_LLM_PLANNER=false`。本文所有真实模型结果均在显式开启后测得，不改变默认线上行为。

## 1. 两段式结构

```text
question
  → rule QueryIR（确定性；品种别名、阶段/指标/疾病归一化、策略路由）
  → [可选] LLM Planner（严格 JSON Schema；意图、显式/推断约束、改写、子问题、置信度）
  → deterministic merge_plan（只接受可验证字段；唯一显式品种才可 hard filter）
  → planner_tasks（子问题 + inherited/applicable constraints + effective_query）
  → 统一 Retrieval Engine（Dense / BM25 / RRF / Reranker / 可选 graph）
```

设计边界：

- **规则 IR 始终先执行**。LLM 失败、超时、返回空、JSON 截断或 schema 不合法时，保留规则 IR，并在 `llm_planner.error` 记录原因；不会静默使用 Mock 生成器。
- **只有唯一、显式出现的品种**可以成为 `species_filter`。LLM 的 `inferred` 品种只作为 soft 信息；`source=explicit&strength=hard` 的非 species 约束会被降级为 `soft_context`，并写 `llm_constraint_not_implemented_as_hard`。
- **年份不是硬过滤**。`requested_year` 仅用于现行规范提示；`published_year`/`effective_date` 仍在 `unsupported_constraints`，不能进入 Qdrant filter。
- **子问题继承是显式字段**。`inherits` 只允许 `species/growth_stage/water_parameters/diseases/year/category`；默认继承 species + growth_stage。子问题原文已经包含某个多值 facet 的一个值时，不再拼接兄弟值（例如原文已说“扣蟹培育”，不会把“生态育苗”硬塞进该子问题）。
- **改写和子问题都会进入统一检索引擎**。`rewritten_query` 和每个 `effective_query` 作为 query variants，与原始问题一起走 Dense/BM25/RRF/Reranker；没有第二套“LLM 检索器”。

## 2. 类型与 trace

`PlannerIR`（Pydantic，`extra="forbid"`）字段：

| 字段 | 用途 |
|---|---|
| `intent` | `fact/complex/regulation/calculation` |
| `species/growth_stage/water_parameters/diseases` | 归一化后的领域 facet |
| `constraints[]` | 每条含 `name/value/source/strength` |
| `assumptions` | 模型推断但未确认的假设 |
| `rewritten_query` | 保留原意的检索改写 |
| `subquestions[]` | `question/facet/inherits`，最多 4 个 |
| `confidence/warnings` | 置信度与不确定项 |

`QueryIR` 新增：

- `planner_tasks[]`：`question/facet/inherits/inherited_constraints/applicable_constraints/effective_query/soft_constraints/source`。
- `planner_constraints[]`：逐条给出 `accepted_as_hard`、`filter_applied`、`scope`。
- `planner_assumptions[]`、`rewritten_query`、`planner_source`、`planner_confidence`。

`status.llm_planner` 记录 `used_llm/error/attempts/duration_ms/plan/original_question/hard_filter/subquestions/tasks/constraints/assumptions`。单 facet 事实问题会带 `skipped=simple_rule_ir` 跳过模型，避免几十秒的无效延迟。

## 3. 可靠性处理

| 场景 | 行为 |
|---|---|
| JSON 截断/语法错误 | 同一轮重试一次，`max_tokens` 增加 1000；仍失败回退规则 |
| schema 不合法/额外字段 | 校验失败；重试后回退规则 |
| HTTP 200 但 `empty content` | 视为 reasoning budget 用尽，重试一次更大 token 预算 |
| 网络/HTTP 错误 | 不重试，直接回退规则 |
| 超过 `planner_timeout_s`（默认 90s） | 取消等待，回退规则，trace 记录 `TimeoutError` |
| 单 facet 问题 | 不调用 LLM，trace `skipped=simple_rule_ir` |

## 4. 真实模型验收

### 4.1 结构化理解探针

- 数据：`eval/planner_probes_v1.json`，10 条**作者工程验收探针**，覆盖多阶段、多品种、跨标准、法规年份、口语别名、数值约束。
- 脚本：`scripts/evaluate_planner.py`。
- 指标：species/stage/water/disease 的集合 F1、意图、hard filter、子问题数；不是人工 qrels，也不能当成事实正确率。

本轮真实运行（前 6 条，P01–P06；模型 `openai-compatible-model`，`planner_max_tokens=2000`，`planner_timeout_s=90`）：

| 指标 | rules | LLM |
|---|---:|---:|
| 字段平均 F1（species/stage/water/disease/intent） | 0.9000 | 0.9333 |
| hard filter 准确率 | 1.0000 | 1.0000 |
| 子问题数量达标率 | 0.0000 | 0.6667 |
| LLM 实际调用率 | — | 1.0000 |
| LLM 回退/错误 | — | 0 |

逐条观察：

- **P03（DB36/DB46 溶解氧比较）**：LLM 把规则 IR 的 `fact` 纠正为 `complex`，并拆出 3 个子问题；字段 F1 从 0.8 到 1.0。这是本轮最明确的收益。
- **P01/P04/P05**：规则字段已经 1.0；LLM 的增量主要是子问题分解（P01 拆成 4 个阶段×指标任务，P04 拆成氨氮/亚硝酸盐/综合三个任务，P05 拆成两个规范检索任务），不是字段识别。
- **P02（对虾/河蟹盐度差异）**：rules 与 LLM 都判成 `fact`，都没有拆子问题；字段 F1 都是 0.8。说明“比较型问题”仅靠当前 prompt 还不够，后续需要显式的 comparison intent。
- **P06（河蟹浮头）**：两者都是 `fact`，LLM 只给了 1 个子问题，未达到探针要求的 2；字段 F1 都是 0.8。
- **安全观察**：P04 的 LLM 子问题文本自行加入了“中华绒螯蟹”（原问题没有品种）；`species_filter` 仍为 `None`，没有变成硬过滤，但这是**软查询偏置**。已在 task 中新增 `unverified_species_in_text` 和 warning `llm_subquestion_added_unverified_species`，不再假装它没有发生。
- 平均墙钟 **59.8 s/题**；这是默认关闭 planner 的直接原因，也说明不能把它放在所有简单问题前面。

> 这 6 条是作者工程探针，不是人工 qrels；P07–P10 尚未跑完，不能把 6 条结果外推成 10 条或论文主表。

### 4.2 检索 A/B

- 脚本：`scripts/evaluate_planner_retrieval.py`。
- 设计：同一批已有 gold 的复杂问题，分别用 `rules` 与 `llm` planner 走同一个 `hybrid_rerank` 检索，比较 Recall@5/10、nDCG@5/10、MRR@10。
- 该实验只测检索，不测答案事实性；答案质量需要单独盲评。

本轮真实运行（R026、R061、R062、R066；`hybrid_rerank`，top_k=10）：

| 指标 | rules | LLM Planner |
|---|---:|---:|
| Recall@5 | 0.6667 | 0.6667 |
| Recall@10 | 0.6667 | 0.6667 |
| nDCG@5 | 0.6683 | 0.6683 |
| nDCG@10 | 0.6683 | 0.6683 |
| MRR@10 | 0.5000 | 0.5000 |

逐条：

- R026、R066：两者都命中 gold，gold 排名不变（R026 第 2，R066 第 1）；LLM 确实生成了 1/2 个 task，但没有改变最终 evidence 排序。
- R062：两者都命中 2/3 个 gold，未命中的 gold 仍是同一 chunk；LLM 的 3 个子问题没有把缺失证据拉进 top 10。
- R061：两者都 0 命中，gold 不在 top 10；这是检索/gold 定位问题，不是“planner 没拆子问题”——LLM 已经拆成 DB36/DB46 两个 task，仍没有命中。

结论：**在这 4 条上，LLM Planner 没有可测量的检索收益**；不能因为结构上更“聪明”就默认启用。该结果也说明后续要查 R061 的 gold/chunk 定位与证据 gate，而不是继续加 prompt。

## 5. 当前限制（必须与前端/论文表述一致）

1. **子问题目前是 query variants，不是独立的证据子图**。统一检索后仍共用全局 document filter；没有按子问题分别 gate。
2. **没有并行 pre-retrieval**。planner 在检索前串行执行；开启后复杂问题会增加数十秒延迟，因此默认关闭。
3. **LLM Planner 的收益不是必然的**。规则 IR 在多约束简单问题上可能同样准确；A/B 必须同时报告 rules 与 LLM，不能只报 LLM。
4. **下游答案质量尚未做盲评**。citation coverage 不是事实正确性；本文不把 lexical overlap 当成 factual correctness。
5. **探针标签是作者工程标签**，需要领域人工复核后才能进入论文主表。

## 6. 复现

```bash
# 只跑结构化理解探针（真实模型，默认 10 条）
cd apps/api
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_planner.py

# 只跑检索 A/B（默认 R026/R061/R062/R066）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_planner_retrieval.py
```

输出在 `eval/runs/planner_probes_v1/` 和 `eval/runs/planner_retrieval_ab.json`；manifest 记录模型、开关、时间、数据 SHA-256（脚本补充后生效）。
