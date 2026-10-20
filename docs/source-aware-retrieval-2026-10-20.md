# Per-task / Source-aware Retrieval（2026-10-20）

> 目标：让 R061（`DB36 和 DB46 两个标准对养殖水体溶解氧的最低要求是否一致？`）
> 的 DB46 gold parent 进入 evidence，且**不写死 gold、不降低 evidence gate 阈值**。
> 实现是确定性的、可解释的；默认开启（`ENABLE_SOURCE_AWARE_RETRIEVAL=true`），
> 可用环境变量关闭做消融。

## 1. 问题定位（真实测量，不是猜测）

R061 的 DB46 gold 是 parent `060eb863…`（DB46 第 7 页，`4养殖环境` 段），它的实际
parent 内容是 **759 字**，前 ~600 字是对虾幼体发育术语表（无节幼体/溞状幼体/糠虾…），
只有最后一段是：

```text
…生产用水应经沉淀、砂滤净化处理后使用。盐度26～35，pH值7.8～8.5，溶解氧含量保持5 mg/L以上。 5养殖设施
```

这带来三个叠加的失败：

| 环节 | 实测 | 后果 |
|---|---|---|
| Dense（BGE-M3） | 在 DB46 单文档内 rank 21（原问题）/ 83（`DB46 溶解氧`） | 向量被术语表主导 |
| BM25 | 单文档内 rank 11（原问题）/ 1（`养殖环境 溶解氧`） | 全局 `bm25_top_k=20` 仍排不进去 |
| Reranker | 用整段 parent 文本时 rank 31/88 | 512 token 截断把末尾的溶解氧句子切掉 |

另外 parent 的 `heading_path` 只有文档名（`纳滨对虾） > 农产品全产业链…`），没有
`4养殖环境`，所以标题/章节也没法救它。

> 结论：这不是 planner 拆不拆子问题的问题；是**候选召回深度 + 文档内竞争 + rerank
> 输入窗口**的问题。任何“把 gold 写进 query”或“降低 gate”的做法都不解决根因。

## 2. 设计：四条可解释规则

1. **只认问题里字面出现的标准号**（`app/query/sources.py`）。
   `DB36`、`DB46`、`GB/T 11607`、`SC/T 1132` 等；不猜、不补全、不查 gold。
   少于 2 个可解析标准号时不启用（单来源问题保持原全局排序），trace 记录原因。
2. **按来源解析文档版本**：用标准号匹配 `kb_documents.title`，得到 active
   `document_version_id`；把检索 filter 收窄到这些版本。DB36/DB46 各自只有一个
   版本，于是“跨文档竞争”消失。
3. **facet 证据要求**：候选 parent 必须包含被问的水质指标（`溶解氧` 也接受文档措辞
   `溶氧量/溶氧`）。这是 evidence requirement，不是 gate——gate 的
   `min_terms=2 / min_weight=3.0 / min_coverage=0.3` 原样保留。若一个来源内没有
   任何候选命中 facet，回退到该来源全池并记录 `fallback_no_facet_match`。
4. **窗口 rerank + 阈值优先**：
   - rerank 输入不是整段 parent，而是 `best_sentence(parent.content, question)`——
     即真正回答问题的证据窗口，避免术语表稀释和 512 token 截断；
   - 同一来源内，含数值阈值的窗口（`以上/以下/不低于/≥/mg/L/ppm/℃/‰`）排在仅提及
     facet 的窗口前面（`确保有足够的溶氧` 不是“最低要求”）。
5. **证据槽位**：`source_anchor_slots=2`，按问题中标准号出现顺序 round-robin
   交错（DB36#1, DB46#1, DB36#2, DB46#2），再拼接全局 rerank 结果、去重、按
   `top_k/max_sources` 截断。

### 与 planner 的关系（per-task）

`planner_tasks` 存在时（LLM planner 打开），全局 rerank 对每个候选取
`max(原问题, task.effective_query)` 的分数，最多 4 个 query；子问题不再只是检索
variant，也参与证据排序。规则 IR 没有 `planner_tasks`，因此默认路径行为不变。

## 3. 真实 trace（R061，`hybrid_rerank`，top_k=10）

```json
"source_aware_retrieval": {
  "enabled": true,
  "cited": [{"code": "DB36", "raw": "DB36", "position": 0},
            {"code": "DB46", "raw": "DB46", "position": 7}],
  "resolved": {"DB36": ["2b5511ca-…"], "DB46": ["9dbe5cbd-…"]},
  "active": true,
  "anchors": [
    {"code": "DB36", "candidates": 34, "facet_filter": "applied",
     "selected": ["e25f6ae4-…", "9029f463-…"], "resolved": true},
    {"code": "DB46", "candidates": 40, "facet_filter": "applied",
     "selected": ["060eb863-…", "70efaaaa-…"], "resolved": true}
  ],
  "slots": 2
}
```

最终 evidence 前 5：

| rank | parent | 来源 | 说明 |
|---:|---|---|---|
| 1 | `e25f6ae4…` | DB36 8.1 水质指标 | **gold**（溶氧量5mg/L以上） |
| 2 | `060eb863…` | DB46 4养殖环境 | **gold**（溶解氧含量保持5 mg/L以上） |
| 3 | `9029f463…` | DB36 5.4 放养方式 | 同文档，仅“确保有足够的溶氧” |
| 4 | `70efaaaa…` | DB46 10.5.1 水质指标 | 同文档，溶解氧5 mg/L以上 |
| 5 | `cf2b2c0d…` | DB46 9.3 水环境要求 | 全局 rerank 第一名（无溶解氧） |

## 4. 结果（同一 gold、`eval/real_questions_v1.jsonl`、top_k=10）

| 指标 | 修复前 rules | 修复前 LLM(alias) | **现在 rules** |
|---|---:|---:|---:|
| Recall@5 | 0.0000 | 0.0000 | **1.0000** |
| Recall@10 | 0.0000 | 0.5000 | **1.0000** |
| nDCG@5 | 0.0000 | — | **1.0000** |
| nDCG@10 | 0.0000 | 0.6131 | **1.0000** |
| MRR@10 | 0.0000 | 0.1429 | **1.0000** |
| child Recall@5 | 0.0000 | — | **1.0000** |

复现命令（cwd 必须是 `apps/api`，否则 `.env` 里的本地 reranker 路径不生效）：

```bash
cd apps/api
python3 - <<'PY'
import json
for line in open('../../eval/real_questions_v1.jsonl'):
    if json.loads(line)['id'] == 'R061':
        open('/tmp/r061.jsonl', 'w').write(line)
PY
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1 \
  .venv/bin/python ../../scripts/evaluate_retrieval_metrics.py \
  --dataset /tmp/r061.jsonl --out ../../eval/runs/r061_source_aware \
  --modes hybrid_rerank --query-ir
```

输出（`eval/runs/r061_source_aware/summary.json`）：

```json
{"recall@5": 1.0, "recall@10": 1.0, "ndcg@5": 1.0, "mrr@10": 1.0,
 "child_recall@5": 1.0, "child_recall@10": 1.0, "avg_retrieval_ms": 4903.0}
```

延迟：独立运行时 R061 约 **4.9 s**（原全局 `hybrid_rerank` 约 1.2 s）；增量来自
2 个来源 ×（dense+sparse）+ 2 次窗口 rerank。只在“问题显式引用 ≥2 个标准号”时触发，
70 题里只有 R061 一条。

## 5. 边界与未做的部分

- **不写死 gold**：来源由问题文本解析，候选由检索产生；gold chunk id 从未进入代码。
- **不降低 gate**：`evidence_min_terms/weight/coverage` 未改；R061 的 gate 仍是
  `matched`，与修复前一致。
- **只解决标准号引用**：按品种比较（如 R062 `中华绒螯蟹 vs 凡纳滨对虾`）还没有
  source anchor；需要“品种 → 标准文档”的唯一映射，另做。
- **chunk 质量是真问题**：`060eb863` 的术语表粘连应在 chunker 修（heading 丢失、
  段落跨节合并），本轮用窗口 rerank 规避，没有改索引。
- **单来源引用不启用槽位**（避免和全局排序打架）；trace 里 `reason` 会写明。