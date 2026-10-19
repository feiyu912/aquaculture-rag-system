# 开发说明（可运行骨架）

> 对应技术方案第 12 节的阶段 1–2 纵向切片。
> 目标不是功能完整，而是把「上传 → 解析 → 切分 → 索引 → 混合检索 → 引用 → SSE」整条链路真实跑通，后续替换模型和组件时不改主流程。

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
| 文档版本更新 | ✅ | 新版本入库成功后才激活，旧版本归档 |
| 版本回滚 | ✅ | 校验 Qdrant 中该版本仍有向量 |
| 引用有效性 / 覆盖率 | ✅ | 确定性校验 + 启发式覆盖率 |
| 引用支持性（NLI/LLM） | ❌ | 下一阶段 |
| PDF.js 区域高亮 | ❌ | 当前只跳转页码；坐标已存好 |
| 会话 / 消息 / 引用持久化 | ✅ | PostgreSQL |
| 查询日志 / 分段耗时 | ✅ | `query_logs` |
| 身份认证 | ❌ | 仅本地开发 |
| 数据库迁移 | ⚠️ | 开发期 `create_all`；改表前补 Alembic |
| 评测脚本 | ❌ | 阶段 9 |

## 2. 环境要求

- macOS / Linux，Python 3.12+
- Docker Desktop（Postgres、Qdrant、Redis）
- [uv](https://docs.astral.sh/uv/)

## 3. 启动

```bash
cd /path/to/aquaculture-rag-system
docker compose -f infra/docker-compose.yml up -d

cd apps/api
cp .env.example .env          # 已存在则跳过
uv sync
uv run python ../../scripts/make_sample_pdf.py
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

## 4. API 快速验证

上传：

```bash
curl -X POST http://127.0.0.1:8000/api/documents \
  -F 'file=@data/samples/aquaculture_sample.pdf;type=application/pdf' \
  -F 'title=水产养殖水质管理示例资料' \
  -F 'category=水质管理'
```

查询任务：

```bash
curl http://127.0.0.1:8000/api/jobs/<job_id>
```

流式问答：

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"中华绒螯蟹养殖对溶解氧有什么要求？"}'
```

历史消息：

```bash
curl http://127.0.0.1:8000/api/sessions
curl http://127.0.0.1:8000/api/sessions/<session_id>/messages
```

## 5. 版本更新与回滚

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

## 6. 测试

```bash
cd apps/api
uv run pytest -q
uv run ruff check app tests ../../scripts
```

当前测试覆盖：坐标归一化、切分、表格父块、RRF、BM25 分词、引用解析与覆盖率、示例 PDF 解析。

## 7. 代码结构

```text
apps/api/app/
  main.py                 FastAPI 生命周期、路由、演示页
  config.py               pydantic-settings 配置
  db.py                   async SQLAlchemy
  models.py               8 张表
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
    vector_store.py       Qdrant collection、过滤、检索
    rrf.py                RRF
    rerank.py             Noop + BGE 适配器
    service.py            两路召回、融合、父块扩展、证据组装
  generation/
    llm.py                Mock 生成器 + DeepSeek 流式适配器
    citations.py          引用解析、有效性、覆盖率
```

## 8. 关键实现说明

### 8.1 为什么 BM25 是应用侧算权重

本地 Qdrant OSS 镜像没有启用 inference service，直接传 `Document(text=..., model="qdrant/bm25")` 会报 `InferenceService is not initialized`。因此当前实现：

1. 用 jieba + 水产自定义词典分词；
2. 在应用侧计算 BM25 词项权重；
3. 写入 Qdrant 稀疏向量，collection 使用 `modifier=idf`。

这仍然是 Qdrant 上的 BM25 稀疏检索，并且分词策略可测试、可复现。后续如果部署环境启用了 Qdrant 原生 BM25，可在 `vector_store.py` 内替换，不影响上层。

### 8.2 开发占位 Embedder

`HashingEmbedder` 用字符/词哈希生成 1024 维向量，只保证流程可跑，**没有语义能力**。切换 BGE-M3：

```bash
uv add FlagEmbedding
# .env
EMBEDDING_MODEL=BAAI/bge-m3
QDRANT_COLLECTION=kb_chunks_bge_m3_v1
```

然后重建集合并重新入库。旧 collection 不要复用，维度/模型都变了。

### 8.3 版本激活顺序

```text
Qdrant upsert → 按版本计数校验 → PostgreSQL 单事务切换 current_version_id → 旧版本 archived
```

任何一步失败，新版本都不会成为当前版本；旧版本继续服务。检索只使用查询开始时读取的生效版本快照。

### 8.4 引用

- 模型只看到 `S1..Sn` 与文本，不接触 bbox。
- 回答结束后解析 `[S1]`、`[1]`、`【1】`、`[S1,S2]`。
- 越界编号记为无效，不静默丢弃。
- `chat_citations` 保存 `quote/page/bbox` 快照，旧版本清理后历史来源仍可展示。
- 覆盖率是启发式指标，用于开发提示，不替代论文中的人工标注。

## 9. 已知限制

1. **Hash embedder 不是 BGE-M3**，检索质量不代表最终系统。
2. **PyMuPDF 解析器只适合文本型 PDF**；扫描件、复杂双栏、公式需要 MinerU。
3. **未接入 Reranker**，当前是 RRF 排序。
4. **DeepSeek 适配器未做真实 Key 验证**；默认 mock 便于离线开发。
5. **没有 PDF.js 高亮**，只有页码跳转；坐标数据已经按规范入库。
6. **没有认证/权限**，不要暴露到公网。
7. **没有旧版本清理任务**，Qdrant 会保留归档版本向量；检索已过滤，不影响正确性。
8. **`create_all` 不是迁移方案**，修改表结构前引入 Alembic。
9. **没有评测集与指标脚本**，阶段 9 完成。

## 10. 下一阶段建议

按依赖顺序：

1. 用 BGE-M3 替换 Hash embedder，建立 `kb_chunks_bge_m3_v1`，重跑同一批问题对比。
2. 接入 MinerU 适配器，用真实 PDF 校准 bbox；保留 PyMuPDF 作为降级。
3. 接入 BGE-Reranker-v2-m3，先测 CPU/GPU 延迟，再定候选数。
4. 完成 PDF.js 查看器：页码跳转 + bbox 高亮 + 多 location 切换。
5. 增加 `reindex` 与旧版本清理任务、Qdrant/PostgreSQL 对账。
6. 建立 200 条人工评测集，先跑检索消融（E1）。
7. 前端迁移到 Next.js，保留当前演示页作为联调工具。

## 11. 常见问题

**Q: 上传后一直 queued。**
检查 worker 是否启动、Redis 是否健康：`docker compose ps`、`uv run arq app.worker.WorkerSettings`。

**Q: 上传返回 409。**
相同 SHA-256 的文件已在库中。删除旧文档后可重新上传；同一文档更新请用 `/versions` 接口。

**Q: 问答返回“现有资料不足以回答”。**
确认文档已成功激活：`GET /api/documents` 的 `current_version_id` 非空，任务状态为 `succeeded`。

**Q: 端口冲突。**
默认 5432/6333/6379/8000；改 `infra/docker-compose.yml` 与 `apps/api/.env` 后同步修改。