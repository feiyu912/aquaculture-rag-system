# 开发说明（可运行骨架）

> 对应技术方案第 12 节的阶段 1–2 纵向切片 + Phase 1 可关闭增强。
> 先把「上传 → 解析 → 切分 → 索引 → 混合检索 → 引用 → SSE」真实跑通，再逐步增加 Query IR、Contextual Retrieval、声明级检查等可选模块。

## 1. 当前实现状态

| 能力 | 状态 | 说明 |
|---|---|---|
| PDF 上传、任务状态 | ✅ | FastAPI + ARQ + Redis |
| PDF 解析 | ✅（开发用） | PyMuPDF 适配器；MinerU 适配器留接口 |
| 坐标归一化 | ✅ | PDF points、左下原点、CropBox、未旋转 |
| 结构感知 + Parent-Child 切分 | ✅ | 标题路径、表格独立父块、跨页 location |
| Dense 检索 | ⚠️ 开发占位 | `HashingEmbedder`，**不是 BGE-M3，不能用于论文实验** |
| BM25 | ✅ | 应用侧 BM25 词项权重 + Qdrant 稀疏向量 IDF |
| RRF | ✅ | 应用侧融合，保留两路排名日志 |
| Reranker | ⏳ | `NoopReranker` 占位；BGE 适配器已写，未启用 |
| 生成 | ✅ / ⏳ | 默认 `mock` 抽取式回答；DeepSeek 适配器已写，需 Key 验证 |
| 检索模式 | ✅ | `dense` / `bm25` / `hybrid` / `hybrid_rerank` 可切换 |
| 多品种元数据 | ✅ | 文档可关联多个品种；Qdrant 品种过滤；问题中自动识别单一品种 |
| Typed Query IR | ✅（规则 v1） | 意图、品种、阶段、水质指标、年份/规范标记；只有可信字段编译为硬过滤 |
| Contextual Retrieval | ✅（可开关） | `context_text` 与原文分开存储；索引文本可切换，引用仍用原文 |
| 声明级引用检查 | ✅（v0） | 回答拆句、映射 `[S1]`、词面支持性；明确不是 NLI |
| 检索 Trace | ✅（本地调试） | `GET /api/debug/query-logs/{request_id}` |
| 图扩展 / 多跳 / 自适应路由 | ⏳ Phase 2 | 本次未接默认链路；先保留开关与 IR/route 接口 |
| 文档版本更新 | ✅ | 新版本入库成功后才激活，旧版本归档 |
| 版本回滚 | ✅ | 校验 Qdrant 中该版本仍有向量 |
| 后台任务恢复 | ✅ | ARQ 重试 + 失败重试接口 + worker 启动回收超时任务 |
| 引用有效性 / 覆盖率 | ✅ | 确定性校验 + 启发式覆盖率 |
| 引用支持性 | ⚠️ | 已留验证接口，当前是词面重叠 v0，**不是 NLI** |
| 证据不足拒答 | ✅ | 词面门槛；域外问题不返回证据、不生成引用 |
| PDF 原文定位 | ⚠️ | 引用可点击到 PDF 页码；bbox 已存，PDF.js 高亮未做 |
| 会话 / 消息 / 引用持久化 | ✅ | PostgreSQL |
| 查询日志 / 分段耗时 | ✅ | `query_logs` 含 rankings、evidence、模型、token、成本 |
| 身份认证 | ❌ | 仅本地开发 |
| 数据库迁移 | ✅（轻量） | `schema_migrations` + 加列迁移；正式环境再换 Alembic |
| 批量评测 | ✅ | `scripts/evaluate.py` + `eval/sample_questions.jsonl`，导出 JSONL/CSV |

## 2. 三个验收场景

| 场景 | 操作 | 已验证 |
|---|---|---|
| A | 上传水产资料 → 提问 → 带来源回答 → 点击引用到 PDF 页码 | `scripts/smoke_test.py` |
| B | 上传同一文档新版本 → 只引用新版本 → 回滚旧版本 | 同上 |
| C | 提问知识库外问题 → 说明证据不足，不编造引用 | 同上 |

```bash
cd apps/api
uv run python ../../scripts/smoke_test.py
# 保留生成的示例文档用于手工演示：
uv run python ../../scripts/smoke_test.py --keep
```

## 3. 环境要求

- macOS / Linux，Python 3.12+
- Docker Desktop（Postgres、Qdrant、Redis）
- [uv](https://docs.astral.sh/uv/)

## 4. 启动

```bash
cd /path/to/aquaculture-rag-system
docker compose -f infra/docker-compose.yml up -d

cd apps/api
cp .env.example .env          # 已存在则跳过
uv sync
uv run python ../../scripts/make_sample_pdf.py
# 建表 + 增量迁移；应用启动时也会自动执行
uv run python ../../scripts/migrate_db.py
```

启动 API：

```bash
cd apps/api
uv run uvicorn app.main:app --reload --port 8000
```

另开一个终端启动 worker：

```bash
cd apps/api
uv run arq app.worker.WorkerSettings
```

打开 <http://127.0.0.1:8000>，上传 `data/samples/aquaculture_sample.pdf`，等待任务完成后提问。

### 常用检查

```bash
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
docker compose -f infra/docker-compose.yml ps
```

## 5. API 快速验证

上传：

```bash
curl -X POST http://127.0.0.1:8000/api/documents \
  -F 'file=@data/samples/aquaculture_sample.pdf;type=application/pdf' \
  -F 'title=水产养殖水质通用资料' \
  -F 'species=通用' \
  -F 'category=水质管理'
```

`species` 用逗号/顿号分隔，可写多个品种；留空等同“通用”。文档的品种会写入 Qdrant payload，检索时作为硬过滤条件；问题中出现唯一品种名（含唯一后缀别名，如“对虾”）时自动启用过滤。

查询任务：

```bash
curl http://127.0.0.1:8000/api/jobs/<job_id>
```

流式问答：

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"中华绒螯蟹养殖对溶解氧有什么要求？","retrieval_mode":"hybrid","species":"中华绒螯蟹"}'
```

`retrieval_mode` 可选 `dense`、`bm25`、`hybrid`、`hybrid_rerank`，用于演示和消融。
`species` 可留空；系统会根据问题自动识别单一品种，识别到两个及以上时不硬过滤。

历史消息：

```bash
curl http://127.0.0.1:8000/api/sessions
curl http://127.0.0.1:8000/api/sessions/<session_id>/messages
```

## 6. 文档版本、回滚与重试

上传同一文档的新版本：

```bash
curl -X POST http://127.0.0.1:8000/api/documents/<document_id>/versions \
  -F 'file=@data/samples/aquaculture_sample_v2.pdf;type=application/pdf'
```

新版本完成解析、切分、向量化并通过数量校验后，才会切换 `current_version_id`；旧版本置为 `archived`。

回滚：

```bash
curl -X POST http://127.0.0.1:8000/api/documents/<document_id>/rollback \
  -H 'Content-Type: application/json' \
  -d '{"version_id":"<old_version_id>"}'
```

回滚会检查该版本在 Qdrant 中是否仍有向量；如果已被清理，返回 409，需要重新索引。

失败任务重试：

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/<job_id>/retry
```

worker 启动时会回收超过 30 分钟仍为 `running`、或超过 60 分钟仍为 `queued` 的任务；同一版本重复入库会先删除该版本旧向量再写入。

## 7. 测试

```bash
cd apps/api
uv run pytest -q
uv run ruff check app tests ../../scripts
```

当前单元测试覆盖：坐标归一化、切分、表格父块、RRF、BM25 分词、引用解析与覆盖率、证据门槛、品种解析/识别、引用支持性接口、检索模式、示例 PDF 解析。

端到端测试（需要 API + worker 运行）：

```bash
uv run python ../../scripts/smoke_test.py
```

批量评测：

```bash
uv run python ../../scripts/evaluate.py \
  --dataset ../../eval/sample_questions.jsonl \
  --modes dense,bm25,hybrid,hybrid_rerank \
  --out ../../eval/runs/demo
```

## 8. 代码结构

```text
apps/api/app/
  main.py                 FastAPI 生命周期、路由、演示页
  config.py               pydantic-settings 配置
  db.py                   async SQLAlchemy + 启动迁移
  migrations.py           schema_migrations 与增量加列
  models.py               8 张表
  species.py              品种解析、识别、通用品种约定
  queue.py                ARQ 连接池
  worker.py               ARQ WorkerSettings
  api/
    documents.py          上传、版本、回滚、文件、任务
    chat.py               SSE 问答、引用持久化
    sessions.py           会话与消息
    health.py             依赖健康检查
  ingestion/
    parser.py             ParsedBlock 规范模型、PyMuPDF 适配器、MinerU 占位
    chunker.py            Parent-Child、表格、位置合并
    embedder.py           Hashing 开发占位 + BGE-M3 适配器
    pipeline.py           解析→切分→向量化→写入→校验→激活
  retrieval/
    bm25.py               中文分词、BM25 稀疏权重
    vector_store.py       Qdrant collection、品种/版本过滤、检索
    rrf.py                RRF
    rerank.py             Noop + BGE 适配器 + 工厂
    sufficiency.py        证据不足门槛（词面 v0）
    service.py            四种模式、融合、父块扩展、证据组装
  generation/
    llm.py                Mock 生成器 + DeepSeek 流式适配器
    citations.py          引用解析、有效性、覆盖率
    support.py            引用支持性接口（词面 v0，非 NLI）
scripts/
  migrate_db.py           建表 + 增量迁移
  smoke_test.py           A/B/C 端到端验收
  evaluate.py             批量评测、导出 JSONL/CSV
eval/
  sample_questions.jsonl  合成测试集（非论文 Ground Truth）
```

## 9. 关键实现说明

### 9.1 为什么 BM25 是应用侧算权重

本地 Qdrant OSS 镜像没有启用 inference service，直接传 `Document(text=..., model="qdrant/bm25")` 会报 `InferenceService is not initialized`。因此当前实现：

1. 用 jieba + 水产自定义词典分词；
2. 在应用侧计算 BM25 词项权重；
3. 写入 Qdrant 稀疏向量，collection 使用 `modifier=idf`。

这仍然是 Qdrant 上的 BM25 稀疏检索，并且分词策略可测试、可复现。后续如果部署环境启用了 Qdrant 原生 BM25，可在 `vector_store.py` 内替换，不影响上层。

### 9.2 开发占位 Embedder

`HashingEmbedder` 用字符/词哈希生成 1024 维向量，只保证流程可跑，**没有语义能力**。切换 BGE-M3：

```bash
uv add FlagEmbedding
# .env
EMBEDDING_MODEL=BAAI/bge-m3
QDRANT_COLLECTION=kb_chunks_bge_m3_v1
```

然后重建集合并重新入库。旧 collection 不要复用，维度/模型都变了。

### 9.3 版本激活顺序

```text
Qdrant upsert → 按版本计数校验 → PostgreSQL 单事务切换 current_version_id → 旧版本 archived
```

任何一步失败，新版本都不会成为当前版本；旧版本继续服务。检索只使用查询开始时读取的生效版本快照。

### 9.4 引用

- 模型只看到 `S1..Sn` 与文本，不接触 bbox。
- 回答结束后解析 `[S1]`、`[1]`、`【1】`、`[S1,S2]`。
- 越界编号记为无效，不静默丢弃。
- `chat_citations` 保存 `quote/page/bbox` 快照，旧版本清理后历史来源仍可展示。
- **有效性 ≠ 支持性**：`citation_check` 只检查编号是否存在；`chat_citations.support_status` 初始为 `unverified`。
- 支持性验证接口：`POST /api/citations/{citation_id}/verify`，请求 `{"claim":"..."}`。当前实现是 `lexical_overlap_v0`，只用于联调和标注辅助，不能报告为事实正确性。
- 覆盖率是启发式指标，用于开发提示，不替代论文中的人工标注。

### 9.5 四种检索模式

`retrieve(..., mode=...)` 内部按模式决定是否发起 Dense / BM25 请求：

| 模式 | 行为 |
|---|---|
| `dense` | 只查 `dense` 向量 |
| `bm25` | 只查 `bm25` 稀疏向量 |
| `hybrid` | 两路独立召回，应用侧 RRF 融合 |
| `hybrid_rerank` | RRF 后接 Reranker；当前默认 `noop`，接 BGE 后才是真正重排 |

四路都写入 `query_logs.retrieval_rankings`，可直接用于消融。

### 9.6 品种可扩展性

- 品种不是枚举，存在 `kb_documents.species text[]`，上传时自由填写，可多个；空值规范为保留值 `通用`。
- Qdrant payload 同步 `species`；检索过滤为 `species = 查询品种 OR 通用`，避免把虾的病害/用药资料混进蟹的问题。
- 问题中出现唯一已有品种（含唯一后缀别名，如“对虾”对应“凡纳滨对虾”）时自动过滤；出现两个及以上品种时不硬过滤，交给回答层讨论。
- 当前品种粒度是**文档级**。混排文档必须拆成品种专档，否则标错会污染过滤；这是数据治理要求，不是代码能自动推断的。

### 9.7 证据不足门槛

`app/retrieval/sufficiency.py` 是保守的词面门槛，不是语义模型：

```text
命中加权词数 >= 2 且 权重 >= 3 且 覆盖率 >= 0.3
或 单查询词且为领域词
```

- 领域词 = 水产自定义词典 + 通用水质词 + 当前知识库品种名。
- 多证据时取并集判断，避免“蟹在 A 块、溶解氧在 B 块”被误拒。
- 未通过时 `evidence=[]`、`sufficient=false`，生成器走资料不足分支，不产生引用。
- 阈值在 `.env` 的 `EVIDENCE_MIN_TERMS` / `EVIDENCE_MIN_WEIGHT` / `EVIDENCE_MIN_COVERAGE`，论文中必须报告。

### 9.8 Typed Query IR（规则 v1）

`app/query/ir.py` 把问题解析为 `QueryIR`：

- 意图：`fact` / `complex` / `regulation` / `calculation`
- 品种、养殖阶段、水质指标、疾病/症状、年份
- `strategy`：`simple` / `semantic_expansion` / `multi_hop` / `regulation` / `calculation`
- 仅当**唯一**品种被确认时编译为 Qdrant 硬过滤；多品种、年份、规范状态只作为软约束/告警
- 明确不支持“把 2026 当成 `published_year=2026`”的偷懒过滤；`unsupported_constraints` 会记录 `published_year`、`effective_date`、`regulation_status`
- 原始问题始终保留在 `original_question`

当前是规则实现，不调用 LLM，因此不会凭空生成品种/日期；LLM IR 可作为后续实验开关。

### 9.9 声明级引用检查（v0）

`app/generation/claims.py`：

- 将回答按段落/句子拆成 claim；
- 映射 claim 中的 `[S1]` / `[1]` 到 source；
- 复用 `lexical_overlap_v0` 判断词面支持；
- 状态：`supported` / `weak` / `unverified` / `uncited`；
- `citation_check.claim_summary` 写入 SSE、`chat_messages.meta`、`query_logs.citation_check`；
- 可重算：`POST /api/messages/{message_id}/verify-claims`。

这只是可解释的 v0 基线，**不能报告为 NLI 或事实正确性**。

### 9.10 Contextual Retrieval（可开关）

- `kb_chunks.context_text` 保存“文档标题 + 章节路径 + 适用品种 + 原文”的索引辅助文本；
- 原始 `content` 不变，引用快照仍来自原文；
- `ENABLE_CONTEXTUAL_RETRIEVAL=true` 时，Dense/BM25 使用 `context_text` 建索引；默认 `false`，便于对照实验；
- 只影响新入库版本；旧版本没有 context 时回退原文；
- `chunk_config_hash` 包含该开关，避免混用不同索引配置。

### 9.11 检索 Trace

`GET /api/debug/query-logs/{request_id}` 返回：

- Query IR、硬过滤、gate、missing terms；
- dense/sparse 排名列表、融合候选数；
- 最终 evidence、引用检查、模型、成本、耗时。

该接口仅用于本地调试，没有鉴权，不要暴露到公网。

## 10. 已知限制

1. **Hash embedder 不是 BGE-M3**，检索质量不代表最终系统。
2. **PyMuPDF 解析器只适合文本型 PDF**；扫描件、复杂双栏、公式需要 MinerU。
3. **Reranker 默认是 `noop`**；`hybrid_rerank` 在接 BGE-Reranker 前等价于 RRF，不要把它当成真实重排结果。
4. **DeepSeek 适配器未做真实 Key 验证**；默认 mock 便于离线开发，所有测试不依赖外网。
5. **没有 PDF.js 高亮**，只有页码跳转；bbox 已按规范入库，前端可后续接高亮。
6. **没有认证/权限**，不要暴露到公网。
7. **没有旧版本清理任务**，Qdrant 会保留归档版本向量；检索已过滤，不影响正确性。
8. **迁移是轻量加列方案**，不是 Alembic；改列类型/删列/复杂回填前必须引入 Alembic。
9. **评测是 page-level 代理指标**，`eval/sample_questions.jsonl` 是合成集，不是论文 Ground Truth；引用支持性尚未做 NLI。
10. **品种过滤是文档级**；混排多种品种的文档必须拆档，否则会污染过滤。
11. **证据不足是词面规则**，会误拒/误放；阈值和失败案例必须写进论文。
12. **表格/跨页 bbox** 只保证规范化和页码降级，不保证每个复杂表格的框都精确。
13. **Query IR 是规则 v1**，不处理复杂否定、指代和隐含条件；LLM IR 尚未接入。
14. **声明级检查是词面 v0**，会把“同词不同义”判成支持，也会漏掉改写；需要 NLI/人工标注验证。
15. **Contextual Retrieval 默认关闭**；开启后必须重建索引，且收益需要在真实数据上验证。
16. **图扩展、多跳分解、自适应 LangGraph 路由尚未实现**；当前只有 IR 的 strategy 字段和确定性 route 函数，不应在论文中声称已完成。

## 11. 下一阶段建议

按依赖顺序：

1. 用 BGE-M3 替换 Hash embedder，建立 `kb_chunks_bge_m3_v1`，重跑同一批问题对比。
2. 接入 MinerU 适配器，用真实 PDF 校准 bbox；保留 PyMuPDF 作为降级。
3. 接入 BGE-Reranker-v2-m3，先测 CPU/GPU 延迟，再定候选数；同时在评测中对比 `hybrid` 与 `hybrid_rerank`。
4. 完成 PDF.js 查看器：页码跳转 + bbox 高亮 + 多 location 切换。
5. 增加 `reindex` 与旧版本清理任务、Qdrant/PostgreSQL 对账。
6. 建立 200 条人工评测集（含 gold chunk / 证据句），跑检索消融 E1；把支持性验证从词面 v0 升级到 NLI 或人工标注。
7. **Phase 2**：实现 PostgreSQL 轻量领域图（实体/别名/关系/来源/审核状态）、Graph-to-Chunk 召回、多查询/问题分解、证据缺口定向补检，并加 `ENABLE_GRAPH_EXPANSION` 等开关。
8. **Phase 3**：用 LangGraph 编排 `SIMPLE / SEMANTIC_EXPANSION / MULTI_HOP / REGULATION / CALCULATION`，加 PDF.js bbox 高亮与 Next.js 前端。
9. 与陶江老师确认品种清单和数据来源后，再扩充品种；当前不预收集几十个品种。

## 12. 常见问题

**Q: 上传后一直 queued。**
检查 worker 是否启动、Redis 是否健康：`docker compose ps`、`uv run arq app.worker.WorkerSettings`。

**Q: 上传返回 409。**
相同 SHA-256 的文件已在库中。删除旧文档后可重新上传；同一文档更新请用 `/versions` 接口。

**Q: 问答返回“现有资料不足以回答”。**
确认文档已成功激活：`GET /api/documents` 的 `current_version_id` 非空，任务状态为 `succeeded`。

**Q: 端口冲突。**
默认 5432/6333/6379/8000；改 `infra/docker-compose.yml` 与 `apps/api/.env` 后同步修改。