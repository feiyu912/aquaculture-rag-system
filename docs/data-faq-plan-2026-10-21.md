# 数据建设与 FAQ 增强：代码审计与最小变更方案

> 日期：2026-10-21。范围：真实代码审计 → 最小变更方案 → 分阶段实施。
> 基线：`164 passed, 2 skipped`（`apps/api` 全量单测，本次改动前）。
> 约束：不重建 collection、不迁移 Elasticsearch、不替换 Qdrant、不新增 Agent 框架、不改 `apps/web`。

## 一、真实代码审计结论

### 1.1 支持的文档格式

| 能力 | 现状 | 证据 |
|---|---|---|
| PDF | ✅ | `api/documents.py:101` 强制 `.pdf` 扩展名；`:114` 校验 `%PDF` 魔数；`ingestion/parser.py:PyMuPDFParser` |
| HTML | ❌ | 无解析器、无 `source_type`、上传接口直接 `415` |
| 扫描件/OCR | ❌ | `MineruParser` 仅占位，`raise NotImplementedError` |

### 1.2 元数据现状

`KbDocument`（`models.py:34`）已有：`title`、`category`、`species[]`、`source_org`、`source_url`、`publish_year`、`doc_metadata`(JSONB: `document_status`/`region`/`original_filename`/`size_bytes`)。

`KbDocumentVersion` 已有：`content_hash`、`file_path`、`page_count`、`parser_name/version`、`embedding_model`、`chunk_config_hash`、`activated_at/archived_at`。

**缺口**（本阶段要补）：

1. 无 `source_type`（pdf/web），无法区分网页与文件；
2. 无 `fetched_at`（抓取时间），网页会变，版本对比失去时间基准；
3. 无 `effective_date`（实施/生效日期），只有 `publish_year`；
4. `document_status` 是自由文本，**不是受控词表**，正式标准/征求意见稿/技术指导/地方建议无法在查询层区分；
5. 无 `growth_stages`（养殖阶段），阶段只能靠全文关键词碰运气；
6. 无跨文档 `supersedes` 关系：同 `doc_id` 内版本管理已有，但"新文件替代旧文件"（不同 doc_id）没有；
7. `region` 存在 JSONB 里，可查询但无索引。

### 1.3 FAQ 可复用的现有资产

| 资产 | 能否复用 | 说明 |
|---|---|---|
| BGE-M3 embedder | ✅ 直接复用 | `get_embedder()` 单例 |
| BM25 稀疏编码器 | ✅ 直接复用 | `BM25SparseEncoder.document_vector/query_vector` |
| Qdrant collection | ✅ 同集合 | 加 payload 字段区分 `source_type=faq`，**不建新 collection** |
| RRF 融合 | ✅ 直接复用 | `rrf.py:rrf_fuse` |
| 版本过滤 | ⚠️ 需扩展 | `vector_store.version_filter()` 目前只接受 `document_version_id` + `chunk_role` |
| Evidence/引用链 | ⚠️ 需扩展 | `Evidence.document_id/version_id` 目前非空 |
| Sufficiency gate | ✅ 原样保留 | FAQ 命中不绕过证据门槛 |
| Trace/QueryLog | ✅ 复用 | `retrieval_rankings` 加 `faq` 键 |

### 1.4 70 题评测集如何存储、如何防污染

- 存储：`eval/real_questions_v1.seed.json`（70 cases，`gold[].doc` 用别名 `crab`/`shrimp`/`db32` + `ordinal`）→ `scripts/build_real_eval_dataset.py` 解析成真实 `chunk_id` → `eval/real_questions_v1.jsonl` + `.manifest.json`（含 `sha256`、`annotation_status`）。
- 现状的隔离能力：**仅有"不在知识库中上传评测题"这一条人工约定**，没有程序化检查。
- 缺口：
  1. 没有 question-cluster 去重，近重复题可被分到两侧；
  2. 没有检查"FAQ 答案文本与测试题 gold 答案高度重合"；
  3. 没有 `usage_scope` 标记，一条 QA 可以同时被导入 FAQ 和测试集。

### 1.5 staging 能力

当前上传即 `status="active"` 且版本立即激活。但检索的活跃版本来自：

```python
select(KbDocument.current_version_id).where(KbDocument.status == "active", ...)
```

**这意味着 `status="staging"` 的文档即使已解析、已写入 Qdrant，也天然不会被检索到。** 不需要新建集合或加过滤条件——这是最小且零风险的 staging 机制。

## 二、合规结论（重要）

| 域名 | robots.txt | 处置 |
|---|---|---|
| `www.moa.gov.cn` | **`User-agent: * / Disallow: /`** | **禁止自动抓取**。登记为 `manual` 策略：只记录 URL/元数据，文件由人工下载后投放到 `data/inbox/` |
| `agri.cn` | 404（RFC 9309：4xx = 无限制） | 允许，限速 1 req/2s |
| `nftec.agri.cn` | 403（RFC 9309：4xx = 无限制） | 允许，限速 1 req/2s |
| `yyj.moa.gov.cn` | 404 | 允许，限速 |
| `fao.org` | 有规则，含 sitemap | 允许，按规则限速 |

采集模块**内置 robots 判定**：`disallow` 时直接拒绝并记录 `robots_blocked`，不提供绕过开关。

## 三、最小变更方案

### 3.1 数据模型（1 个迁移，向后兼容）

```text
kb_documents          + source_type(pdf|web)  authority_level  fetched_at
                      + effective_date  growth_stages text[]  supersedes_document_id
                      status 取值新增 'staging'（active|staging|deleted）

faq_entries           新表
  id, question, answer, question_norm, question_hash
  species text[], topic, growth_stages text[], region
  source_dataset, original_id, original_source_url, source_license
  supporting jsonb            -- [{document_id, version_id, chunk_id, page, quote, score}]
  evidence_status             -- none|partial|supported|conflict
  review_status               -- pending|verified|rejected（默认 pending）
  usage_scope                 -- knowledge|dev|eval（默认 knowledge）
  confidence, review_notes, content_hash, indexed_at

chat_citations        ALTER document_id/document_version_id DROP NOT NULL
                      + source_type(default 'document')  + faq_id

data_runs             新表（采集/导入运行报告）
  id, kind(crawl|faq_import|index), status, params jsonb, stats jsonb,
  error_message, started_at, finished_at
```

**不改**：`kb_chunks`、`index_manifests`、`query_logs`、`graph_*`。

### 3.2 解析与采集

| 模块 | 变更 |
|---|---|
| `ingestion/html_parser.py` | 新增。正文抽取 → `ParsedBlock`；`location` 用 `{coordinate_system:"web_text", url, anchor_text, section}` |
| `ingestion/format.py` | 新增。按魔数/Content-Type 判定 `pdf|html` |
| `ingestion/pipeline.py` | 解析器按 `source_type` 选择；`_activate` 尊重 `staging`（不置 active） |
| `collection/robots.py` | 新增。robots 拉取 + 判定 + 缓存；无 UA 绕过 |
| `collection/fetch.py` | 新增。限速、UA、重试、内容哈希、sidecar 元数据、`manual` 策略拒绝 |
| `collection/registry.py` | 新增。YAML 源清单（URL/机构/发布日期/效力等级/品种/地区/策略） |
| `scripts/collect_sources.py` | 新增 CLI。`--dry-run` / `--limit` / `--only` |

### 3.3 FAQ 流水线

```text
HF parquet → 关键词初筛 → 领域判定（非仅关键词）→ 分类
→ 清洗 → 精确去重 → 语义近重复（question-cluster）
→ 质量规则检测 → 证据检索匹配 → 写入 faq_entries(pending)
```

- `app/faq/normalize.py`：归一化（全半角/标点/空白/别名）、hash、char-3gram MinHash 近重复。
- `app/faq/quality.py`：空答/过短/无来源数值/单位异常/时效词/品种不明/AI 生成特征 → `quality_flags`。
- `app/faq/evidence.py`：调 `retrieve()` 取 top-k chunk 作候选证据，记录 `evidence_status`。
- `scripts/import_faq.py`：可复现导入，`--limit 200` 试点。

**关键约束**：`confidence` 只作排序提示，**不能**把 `review_status` 从 `pending` 改成 `verified`；只有人工审核接口能改。

### 3.4 检索集成（复用同一引擎）

- `vector_store.version_filter()` 增加 `include_faq`：`should=[document 分支, faq 分支]`。
- `vector_store.upsert_faq()/delete_faq()`：写入同一 collection，payload `source_type="faq"`、`review_status`。
- `Evidence` 扩展：`source_type`、`faq_id`，`document_id/version_id` 可为 `None`。
- `retrieve(..., include_faq=False)`：默认关；开启时 FAQ 分支与 dense/sparse 并行，参与同一 RRF。
- 只有 `review_status="verified"` 的 FAQ 才进索引（pending 不入 Qdrant，避免未核验内容被检索）。

### 3.5 回答模式（默认不变）

```python
answer_mode: "document_rag" | "document_faq_rag" | "faq_direct"  # 默认 document_rag
```

| 模式 | 行为 | Feature Flag |
|---|---|---|
| `document_rag` | 现状，完全不变 | — |
| `document_faq_rag` | 文献 + 已核实 FAQ 混合证据，LLM 综合 | `ENABLE_FAQ_RETRIEVAL` |
| `faq_direct` | 严格条件下直接返回已核实答案 | `ENABLE_FAQ_DIRECT_ANSWER` |

`faq_direct` 的准入（**全部满足**，缺一回落到完整 RAG 并记录 `fallback_reason`）：

1. `review_status=verified`；
2. 问题归一化后与 FAQ 问题的 **BM25 与 Dense 双路** 排名均 top-1 且分数过阈值（不单凭向量分）；
3. 品种/阶段/地区条件与用户问题不冲突（FAQ 条件为空视为通用；用户指定品种时 FAQ 必须匹配或为通用）；
4. 无 `conflict` 证据、`evidence_status in {supported, partial}`；
5. 问题不含复杂条件标记（多品种对比、计算、法规时效等）→ 否则走完整 RAG。

FAQ 直答同样产出 `ChatCitation`（`source_type="faq"`），可追溯。

### 3.6 隔离与泄漏检查

- `scripts/check_eval_leakage.py`： 
  - 题目归一化精确重复；
  - char-3gram Jaccard ≥ 0.8 近重复；
  - FAQ 答案与测试 `reference_answer` 的 token 重合率 ≥ 0.7 告警；
  - `usage_scope="eval"` 的记录出现在 FAQ 索引中 → 直接失败。
- 导入时强制 `usage_scope` 默认 `knowledge`；评测题来源标注 `eval`。
- 评测 manifest 增加 `leak_guard` 字段记录检查时间与结果。

### 3.7 评测

新增 `scripts/evaluate_faq_modes.py`：相同测试集、固定配置，跑 A/B/C 三配置，输出逐题 JSONL + 汇总 CSV + 错误分析。指标：Recall@5/10、MRR、nDCG@10、回答正确率（人工/规则）、引用支持率、条件覆盖、正确拒答率、P50/P95、token 与成本。

### 3.8 API（向后兼容，只增不改）

新增：

```text
GET  /api/data/sources            数据源登记与 robots 状态
GET  /api/data/runs               采集/导入运行报告
GET  /api/faq?review_status=       FAQ 列表
GET  /api/faq/{id}                 FAQ 详情 + 证据链
POST /api/faq/{id}/review          人工审核（pending→verified/rejected）
POST /api/documents/{id}/promote   staging → active
```

扩展（不破坏旧客户端）：`GET /api/documents` 增加 `source_type`、`authority_level` 过滤；`ChatRequest` 增加 `answer_mode`；`sources[]` 增加 `source_type`/`faq_id`。

## 四、实施顺序

| 阶段 | 内容 | 验收 |
|---|---|---|
| P1 | 迁移 + 模型 + staging | 迁移幂等；旧数据不受影响；164 测试仍绿 |
| P2 | HTML 解析 + 采集模块 | 真实抓取 20–30 份；robots 拒绝 moa 自动抓取 |
| P3 | FAQ 导入 + 证据匹配 | 100–200 条 pending，含质量统计与问题清单 |
| P4 | FAQ 索引 + 检索集成 + 回答模式 | 三模式可切换；默认行为不变 |
| P5 | 泄漏检查 + A/B/C 实验 | 三组结果 + 错误分析 |
| P6 | API + Contract 文档 | 旧契约不变；新增端点有示例 |