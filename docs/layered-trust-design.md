# 分层可信证据与知识污染防护

> 版本：2026-10-21
> 范围：`apps/api` 检索与数据层；不改动 `apps/web`
> 结论先行：加入 120 条未核验第三方 QA、17 篇采集文档后，默认问答仍只引用 L1 原始文献；未核验 QA 的可引用条目数为 **0**；对照实验 D（取消隔离）的污染率为 **28.9%**，A/B/C 为 **0.0%**。

## 1. 不可协商的约束

1. 不按文件格式判断可信度，按**来源机构、资料性质、适用范围、发布日期、版本有效性、可追溯性**判断。
2. 不重建检索栈：保留 Qdrant、BGE-M3、BM25、RRF、Reranker、Evidence Sufficiency、DeepSeek、Citation Verification。
3. 不为"能答出来"而降低充分性阈值；证据不足时宁可拒答。
4. 未核验 QA 不得进入默认可信证据检索范围，不得挤占 Top-K。
5. 任何新增网页资料必须记录来源并人工核验后才能成为权威证据。

## 2. 四级来源模型

| 级别 | 含义 | 可否作为证据 | 落地位置 |
|---|---|---|---|
| `L1_original` | 可追溯原始文献：现行标准、官方技术指南、公开科研资料 | ✅ 主要证据 | `kb_documents` + Qdrant `chunk_role=child` |
| `L2_verified_faq` | 人工核验、且支撑文献仍 active 的 FAQ | ✅ 补充证据（仅 L1 不足时） | `faq_entries` + Qdrant `chunk_role=faq` |
| `L3_unverified_qa` | 公开 QA 数据集（HuggingFace 等） | ❌ 永不作为证据 | 仅 PostgreSQL，**不进 Qdrant** |
| `L4_history` | 历史对话、历史模型回答 | ❌ 永不作为证据 | `chat_messages` |

可信度不是单一的"权威等级"。`L1` 内部仍按 `authority_level` 分层（见 `app/authority.py`）：

- 约束性：`national_standard`、`industry_standard`、`local_standard`
- 非约束性：`standard_draft`（征求意见稿）、`historical`、`synthetic`、`unknown`
- 官方技术文件：`official_technical`
- 国际/科研：`international`、`peer_reviewed`

`evidence_eligible()` 会直接拒绝**非约束性**等级，因此征求意见稿不会被当作现行规范引用。

## 3. 数据模型

### 3.1 `kb_documents` 新增

| 字段 | 用途 |
|---|---|
| `source_type` | `pdf` / `web` |
| `authority_level` | 受控词表，见上 |
| `verification_status` | `verified` / `pending` / `rejected`；**手工上传默认 verified，采集入库强制 pending** |
| `source_url`、`source_org` | 发布机构与原文地址 |
| `fetched_at`、`effective_date` | 抓取时间 / 生效日期（时效判断） |
| `supersedes_document_id`、`superseded_by_document_id` | 版本链条；被替代的文档不可作为证据 |
| `species`、`growth_stages`、`region` | 适用范围（applicability） |

### 3.2 `faq_entries`

`review_status`、`usage_scope`（`knowledge`/`dev`/`eval`）、`supporting[]`（chunk 级证据）、`evidence_status`、`quality_flags`、`source_authority`、`original_answer`、`indexed_at`。

`usage_scope="eval"` 的条目在复核接口处直接 409，杜绝"评测题变成知识库答案"。

### 3.3 Qdrant payload 新增

`source_type`、`source_authority`、`verification_status`、`evidence_level`、`publisher`、`effective_date`、`growth_stages`、`region`。

检索过滤因此可以在 Qdrant 内部完成，而不是"先取回来再排序"——后者正是污染的来源。

## 4. 索引隔离：为什么用同一个 Collection

**选择**：不新建 collection，靠 payload 契约隔离。

理由：

- 现有 collection 已有 manifest 校验（`index_manifest`）、快照、清理逻辑；多一个 collection 就要复制一整套一致性机制。
- Qdrant 过滤是**结构性**的：文档查询的 filter 必含 `document_version_id ∈ active_versions`，而 FAQ 点没有这个字段；FAQ 查询必含 `source_type="faq"`。两者在布尔过滤层面互斥，不依赖相似度排序。

**验证方式**：

```python
# apps/api/tests/test_trust_layers.py
def test_document_filter_can_never_match_faq_points():
    flt = version_filter([uuid.uuid4()])
    assert "document_version_id" in {c.key for c in flt.must}
    assert {c.key: c for c in flt.must}["chunk_role"].match.value == "child"

def test_faq_filter_requires_verified_and_faq_source_type():
    ...
```

外加真实数据核对：`source_type="faq"` 的点位 6 个，均 `verification_status=verified`、`chunk_role=faq`；文档检索返回的来源中 `source_type` 全为 `document`。

## 5. 检索流程（两阶段）

```text
question
  │
  ├─ L1 检索（dense + BM25 + RRF + 可选 rerank，source-aware / QueryIR / graph）
  │     ├─ 适用性过滤：问题物种 ∩ 文档物种（通用文档放行）
  │     ├─ 严格主题过滤：用药/剂量/禁用/诊断 → 仅接受 binding / official_technical
  │     └─ Evidence Sufficiency 判定（阈值不变）
  │
  ├─ 充分 → 直接生成（FAQ 完全不参与，连查询都不发起）
  │
  └─ 不充分且 ENABLE_FAQ_RETRIEVAL=true
        ├─ FAQ 检索（同时命中 dense 与 BM25 才保留）
        ├─ 丢弃：未核验 / 被替代 / 适用条件冲突 / 支撑版本已不 active
        ├─ 严格主题额外要求 FAQ 支撑为权威来源
        ├─ 追加在 L1 之后（最多 2 条，绝不顶替原文）
        └─ 用同一阈值重算充分性；仍不足 → 拒答
```

关键点：FAQ 是**追加**而非**竞争**。`evidence = [*document_evidence, *faq_evidence]`，且只在 `gate.sufficient == False` 时执行，因此 FAQ 不存在"挤占 Top-K"的路径。

## 6. 八条防污染规则的实现位置

| # | 规则 | 实现 | 测试 |
|---|---|---|---|
| 1 | 未核验 QA 不进默认可信检索 | L3 不入 Qdrant；`upsert_faq` 对非 verified 抛 `UnverifiedFaqError` | `test_upsert_refuses_unverified_faq` |
| 2 | 未核验 QA 不占 Top-K | FAQ 仅在 L1 不足后追加，`faq_supplement_k=2` | `test_faq_supplement_respects_cap` |
| 3 | RRF/Embedding/Reranker 分数不能替代真实性 | 检索后仍是 `evidence_eligible()` + `applicability_conflict()` 硬判定 | `test_no_authority_can_rescue_a_low_trust_level` |
| 4 | 新网页先记录来源再核验 | 采集入库 `status=staging` + `verification_status=pending`；发布接口才置 active | `promote` 409 分支 |
| 5 | FAQ 与原文冲突不按相似度取舍 | 冲突时 `conflict_between_faq_and_document()` 判权威差；FAQ 永不被优先 | 单元测试 + 设计约束 |
| 6 | 历史答案不得自动升级 | 复核接口是唯一 `verified` 入口，且要求 active 支撑 | `test_pending_faq_is_not_usable_as_evidence` |
| 7 | 用药/禁用/病害处置更严格 | `is_strict_question()` + `STRICT_AUTHORITIES`，文档与 FAQ 双侧过滤 | `test_strict_topic_*` |
| 8 | 网页指令性文本不得当命令 | 证据块以"资料"形式拼接，SYSTEM_PROMPT 明确只引用不执行 | 提示词约束（后续可加注入测试） |

## 7. 已落地数据（2026-10-21）

| 项目 | 数量 | 说明 |
|---|---|---|
| 源清单 | 22 | 9 官方技术文件 + 12 国际开放获取 + 1 征求意见稿 |
| 成功采集 | 20 | 2 条 DSpace 条目无 PDF bitstream，如实记失败 |
| 采集文档入库 | 17 篇（9 HTML + 8 PDF） | 全部 `status=staging`、`verification_status=pending` |
| staging chunks | 5,154（子块 3,949 / 父块 1,205） | 已索引但检索不可见 |
| 已发布文档 | 6 篇（3 地方标准 + 3 示例） | 原有语料，`authority_level` 已补全 |
| 未核验 QA | 120 条 `pending` | 0 条进入 Qdrant |
| 已核验 FAQ | 4 条（另 2 条因泄漏评测集已撤回） | 答案逐字来自 active 文档 chunk，可追溯到页码 |

staging 隔离有效性：`_active_version_rows()` 只取 `status="active"` 文档的 `current_version_id`，因此 5,154 个 staging 子块虽然存在于 Qdrant，但不在任何检索的过滤集合内。

## 8. 回答模式（`answer_mode`）

| 值 | 检索行为 | 开关 |
|---|---|---|
| `document_rag`（默认） | 只用原文，FAQ 阶段**不发起**查询 | 无 |
| `document_faq_rag` | 原文不足时追加已核验 FAQ（≤2 条，不顶替原文） | `ENABLE_FAQ_RETRIEVAL` |
| `faq_direct` | 原文不足且单条 FAQ 满足全部严格条件时直接作答，否则回退 | 另需 `ENABLE_FAQ_DIRECT_ANSWER` |

请求只能**收窄**能力：全局开关关闭时，`document_faq_rag`/`faq_direct` 返回 400，不能被请求体强行打开。

`faq_direct` 的五个条件（`app/retrieval/direct.py`，任一不满足即回退并记录 `fallback_reason`）：

1. 已核验，且支撑版本仍在 active 文档上；
2. dense 与 BM25 **同时排第一**（单一向量命中一律不直答）；
3. 物种/生长阶段/地区与问题不冲突；
4. 严格主题（用药、剂量、禁用、诊断）要求支撑为约束性标准或官方技术文件；
5. 答案不含"如果/视情况/分阶段/取决于"等条件句。

回退不降低阈值：`faq_direct` 失败后就回到 `document_faq_rag` 的同一套 Evidence Gate。

## 9. A/B/C/D 对照实验

设置：`eval/real_questions_v1.jsonl` 抽 30 条可回答问题 + 8 条**故意与现行标准冲突的污染探针**（如"河蟹溶氧 1mg/L 即可""pH 9.5–10 最利蜕壳"），共 38 题。FAQ 能力全局开启，A/B/C 仅由 `include_faq` 区分。

| 模式 | 原文引用率 | 污染率 | 拒答率 | 平均证据数 | FAQ 阶段触发 | FAQ 采纳 | P50 |
|---|---|---|---|---|---|---|---|
| A 仅可信原文 | 0.974 | **0.000** | 0.026 | 4.87 | 0 | 0 | 52.4 ms |
| B 原文 + 已核验 FAQ | 0.974 | **0.000** | 0.026 | 4.87 | 1 | 0 | 51.9 ms |
| C 原文 + 未核验 QA 仅做查询扩展 | 0.921 | **0.000** | 0.026 | 4.87 | 0 | 0 | 56.7 ms |
| D 不隔离混合（对照，不上线） | 0.974 | **0.289** | 0.026 | 4.87 | 0 | 0 | 50.4 ms |

解读：

- **D 的 28.9%**：取消隔离后，38 题中有 11 题会被语义相近但错误的 QA 命中。这是隔离要防的具体损失。
- **A/B/C 污染率 0**：未核验 QA 一条都没有进入证据包；A 与 C 的 FAQ 阶段触发数为 0，说明 `document_rag` 连查询都不发。
- **B 触发 1 次、采纳 0 条**：唯一一个原文不足的问题是"DB36/T 2225—2026 的病害防治原则和用药依据"，4 条已核验 FAQ 都不覆盖它，因此正确回退。这不是 B 失效，而是 FAQ 语料尚未覆盖该问题——**且不能为它补 FAQ**，因为它就在评测集里。
- **C 下降 5.3 个百分点**：查询扩展引入噪声词。L3 做"线索"也必须限幅，当前 top-2 仍偏宽。

## 10. 评测集泄漏检查

`scripts/check_eval_leakage.py` 做三类比对（归一化精确相等、字符 3-gram Jaccard ≥ 0.8、参考答案重合 ≥ 0.7），并按处置状态分级：

| 状态 | 级别 | 含义 |
|---|---|---|
| `verified` 或已索引 | critical | 模型可直接检索到测试题答案，该题指标作废 |
| `pending` | warning | 当前不可检索，但必须在复核时排除 |
| `rejected` | mitigated | 已撤下，留档 |

**实测抓到真实泄漏并已处置**：两条从 DB36 原文逐字种子化的 FAQ（溶氧量、pH）与评测参考答案重合 0.87，被判 critical。处置是**撤回**（`review_status=rejected`、从 Qdrant 删除），而不是放宽阈值。复检结果：`exact=0 near=0 critical=0`。

这条经验写进流程：**用评测集金标文档去种子化 FAQ，必然泄漏**；FAQ 若参与 B 组评测，必须来自评测集未覆盖的文档，或采用簇级切分。

## 11. 已知局限

1. **B 组尚无增益证据**：已核验 FAQ 仅 4 条，且刻意避开评测集；38 题中只有 1 题触发 FAQ 阶段且未被覆盖。下一步需用 FAQ 来源问题构建独立测试集（簇级切分），才能报 B 的增量。
2. **通用词跨物种**：如"鱼类冬季聚集深水"仍可能匹配到对虾资料——`species_in_text` 只能识别具体物种，泛称"鱼类"不触发过滤。已在 FAQ 证据匹配中观察到，需在严格主题或审核环节兜底。
3. **冲突检测是启发式**：`conflict_between_faq_and_document()` 只比较权威等级，没有 NLI。真正的矛盾句检测未实现。
4. **提示注入未做自动化测试**：规则 8 目前只靠 prompt 约束。
5. **D 模式是模拟**：污染探针按 token 重叠判定命中，不是真实向量检索。若要把 D 作为论文中的对照，应另建隔离实验 collection 实测。

## 12. 复现命令

```bash
cd apps/api

# 1) 采集（尊重 robots，2s/域名限速）
uv run python ../../scripts/collect_sources.py

# 2) 入库到 staging（不激活）
uv run python ../../scripts/ingest_inbox.py

# 3) 人工核验后发布
curl -X POST http://127.0.0.1:8000/api/documents/<id>/promote \
  -H 'Content-Type: application/json' \
  -d '{"reviewer":"陶江","note":"已核对原文"}'

# 4) 导入未核验 QA（只进 pending，不索引）
uv run python ../../scripts/import_faq.py --limit 120 --match-evidence

# 5) 从 active 文档种子化少量已核验 FAQ
uv run python ../../scripts/seed_verified_faq.py

# 6) 评测集泄漏检查（critical 时退出码 1）
uv run python ../../scripts/check_eval_leakage.py

# 7) A/B/C/D 对照
uv run python ../../scripts/evaluate_trust_modes.py --limit 30
```

产物：`data/reports/trust_modes_report.json`、`data/reports/collect_report.json`、`data/reports/ingest_report.json`、`data/reports/faq_import_report.json`。