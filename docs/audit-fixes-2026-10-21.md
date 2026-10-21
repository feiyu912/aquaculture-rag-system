# 独立审计问题修复记录（2026-10-21）

对应 [codex-independent-full-audit-2026-10-20.md](codex-independent-full-audit-2026-10-20.md)。
本轮只做用户指定的优先级：**scorer → 证据门槛 → 异常/断流终态**；构建冻结与引用身份
绑定见第 3 节的状态说明。所有数字来自本机真实运行，命令见第 4 节。

## 1. 已修复

### F01 / P0：nDCG 丢掉真实排名（`de6b8c2`）

- 旧实现先过滤到 gold 再算 DCG，`["wrong","correct"]`、grade=2 会得 1.0；正确值
  `1/log2(3)=0.6309`。
- 修复：按原位置 `gold.get(id, 0)`，入口对 ranked 去重；脚本删除重复实现，统一用
  `app.evaluation.retrieval_metrics.score_ranking`。
- 用已保存排名重算，未重跑检索/LLM：reranker nDCG@10 **0.9354 → 0.8675**，BM25
  **0.9328 → 0.8398**（旧“仅差 0.0026”不再成立，新差距 0.0277）；Contextual reranker
  增益 +0.0195 → +0.0094；Planner A/B 规则 0.8105/0.8213、LLM 0.7780/0.7912；R061 仍
  1.0。完整表见 [ndcg-correction-2026-10-21.md](ndcg-correction-2026-10-21.md)。

### F02 / P0：高风险“完整清单”被词项相关性放行（本轮最小保护）

审计反例 `水产养殖禁用渔药完整清单有哪些？` 修复前 `matched` + 5 条来源。现在
`assess_evidence` 在返回 `matched` 前加一道确定性检查：

- 问题同时含“清单/名录/名单/目录” + “完整/全部/所有/有哪些” + “禁用/禁药/渔药/兽药/药残/违禁”；
- 证据里必须有一句显式声明（`清单如下/名录如下/目录如下/完整清单/完整名录/共列出`），
  且不能是“未列出完整/不完整/未包含全部”这类否认；
- 否则返回 `sufficient=false, reason=list_completeness_unverified`，`sources=[]`；
  `build_targeted_queries` 对 `complete_list` 缺口直接返回空目标，不做补检索。

真实检索复核（本机 Qdrant/DB，非 mock）：

```text
水产养殖禁用渔药完整清单有哪些？ | sufficient=False reason=list_completeness_unverified sources=0
禁用渔药完整清单有哪些？         | sufficient=False reason=list_completeness_unverified sources=0
扣蟹培育池塘条件包括哪些方面？   | sufficient=True  reason=matched sources=10
DB36和DB46对溶解氧的要求是否一致 | sufficient=True  reason=matched sources=10
```

70 题回归：拒答集合不变（R017/R036/R063/R064/R065），唯一变化是 R064 的原因从
`current_regulation_unverified` 变成 `list_completeness_unverified`；65 道可作答题
全部仍 `matched`。

**边界（未解决）**：这是词面规则，不是语义完整性判断；没有来源等级/版本状态/适用范围
校验，也没有“清单是否真的完整”的事实核对。`generation/support.py` 的否定/单位/主体
冲突仍未处理，后验校验仍在答案流出后执行。审计 F02 的完整方案需要来源等级 + 人工/
校准蕴含评估，本轮没有做。

### F06 / P1：检索失败路径二次报错

- 根因：`_persist_failure(retrieval=None)` 里 `retrieval.config.get(...)` 无保护。
- 修复：route 取值加 None 保护；模型初始化/planner/retrieve 合并进一个 try，任何异常
  先落 `failed` 再抛 503；`_persist_failure` 自身失败只记日志，不覆盖原始异常，保留
  partial 文本。

### F07 / P1：上游缺完成标记仍按成功持久化

- 修复：跟踪 `[DONE]`、`finish_reason` 和 error 帧。`length`/`content_filter` 抛
  `LLMError`；EOF 既无 `[DONE]` 也无 `stop` 抛错；error 帧直接抛。已产出的 token 保留，
  chat 层把消息落成 `failed` 并带 partial。
- 测试：`tests/test_llm_stream.py` 5 例（正常 done、仅 stop、length 截断、裸 EOF、
  error 帧）；`tests/test_chat_failure_states.py` 3 例（无 retrieval、有 retrieval、
  DB 写失败）。

## 2. 验证

```text
pytest: 177 passed, 2 skipped
ruff check（改动文件）: All checks passed
真实检索 4 条探针: 见上
70 题 gate 复核: 1 处原因变化，无新增拒答
```

## 3. 未修复项与原因

| 编号 | 状态 | 说明 |
|---|---|---|
| F03 认证/隔离 | 未改 | 仍定位受控本地演示；共享/公网部署前必须补身份、所有权、CORS 与端口约束 |
| F04 引用身份绑定 | 未改（前端） | 需 `(messageId, sourceIndex)` 选择来源，属 `apps/web/**`，由前端侧处理 |
| F05 构建漂移 | 未改 | 审计明确建议**不要**在当前版本重跑 ingestion；需独立候选索引 + golden diff，属迁移决策 |
| F08 标签侧信息 | 未改 | 需要拆“query-only 主评测”和“用户指定过滤的条件评测”两套口径 |
| F09 图谱可追溯 | 未改 | seed 边 provenance 为人工维护，仍需证据级多跳验证 |
| F10/F11/F12/F14–F21 | 未改 | 版本激活、CropBox、跨页引用、重排阻塞事件循环、retention 调度、成本统计等 |

F13 的表述已在 [planner-ab-70q-2026-10-20.md](planner-ab-70q-2026-10-20.md) 更正：
“0.8 子问题合格率”改为“数量达标率”，并注明只检查 `len(subquestions) >= min`，不校验语义。

## 4. 复现命令

```bash
cd apps/api
.venv/bin/python -m pytest -q
.venv/bin/python ../../scripts/recompute_ndcg.py
```

真实检索探针（节选，需 Qdrant/Postgres 与 BGE 模型就绪）：

```python
r = await retrieve(db, "水产养殖禁用渔药完整清单有哪些？", embedder, bm25,
                   reranker=reranker, top_k=10, mode="hybrid_rerank")
# r.sufficient == False, r.gate["reason"] == "list_completeness_unverified", r.evidence == []
```