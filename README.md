# 水产养殖 RAG 知识问答系统

本科毕业设计项目：**《基于检索增强生成的水产养殖知识问答系统设计与实现》**

> 当前状态：**技术方案 v1.0 已定稿；可运行纵向切片 + 四个验收场景的关键补强已完成。**
> 方案基线见 [技术方案](docs/technical-plan.md)，启动方式见 [开发说明](docs/development.md)。

## 项目定位

面向水产养殖专业知识查询，构建一个可更新、可追溯、可评测的 RAG Web 系统：

- **混合检索**：BGE-M3 Dense + Qdrant BM25 → RRF → BGE-Reranker-v2-m3
- **知识更新**：文档与版本分离，版本化索引，激活后异步清理旧版本
- **可验证引用**：Source ID 映射、引用有效性校验、证据支持性评估、PDF 原文定位
- **轻量工作流**：LangGraph 只负责路由、必要重试和证据不足分支
- **可复现实验**：检索消融、回答质量、引用可靠性、系统性能四组实验

## 当前骨架已验证

```text
上传 PDF → ARQ 任务 → PyMuPDF 解析 → 坐标归一化 → Parent-Child 切分
→ Dense(开发占位) + BM25 → Qdrant → RRF → 父块扩展
→ Mock/DeepSeek 生成 → 引用解析 → SSE → PostgreSQL 持久化
```

已跑通：

- 上传、任务状态、文档列表、PDF 原文访问
- 同一文档上传新版本，成功后才切换生效版本；旧版本归档
- 回滚到旧版本，并校验 Qdrant 中该版本向量仍存在
- 查询时固定生效版本快照，引用记录版本号与 `quote/page/bbox` 快照
- 引用有效性校验、启发式事实引用覆盖率、分段耗时日志
- 四种检索模式：`dense` / `bm25` / `hybrid` / `hybrid_rerank`（用于消融）
- 文档级多品种元数据与 Qdrant 过滤；问题中出现唯一品种时自动过滤
- 证据不足门槛：域外问题不返回证据、不生成引用
- 引用支持性验证接口（当前 `lexical_overlap_v0`，不是 NLI）
- 查询日志保留两路排名、证据、模型、token 与成本
- 轻量增量迁移、失败任务重试、worker 启动回收超时任务
- **Typed Query IR（规则 v1）**：意图/品种/阶段/水质指标/年份标记，硬约束确定性编译
- **Contextual Retrieval（可开关）**：索引辅助文本与引用原文分离
- **声明级引用检查（v0）**：句子级 `[S1]` 映射与词面支持性，不冒充 NLI
- **轻量领域图（可开关）**：人工审核种子实体/别名/关系、chunk mention、一跳扩展、Graph-to-Chunk
- **规则问题分解（可开关）**：多指标问题拆 facet 子查询，继承硬约束并参与 RRF
- **证据要求 + 定向补检（可开关）**：facet 缺口检查、最多一次补充检索
- **确定性自适应路由（可开关）**：计算/现行规范缺少工具或日期元数据时安全拒答
- **检索 Trace**：按 request_id 查看排名、证据、IR、gate 与耗时
- 67 个单元测试 + A/B/C 端到端冒烟测试 + 批量评测 CLI

> ⚠️ 当前 Dense 使用 `HashingEmbedder` 开发占位，**不是 BGE-M3，不能用于论文实验**。
> PyMuPDF 只是 MinerU 的临时降级解析器。Reranker 默认 `noop`；PDF.js 高亮、真实 DeepSeek 调用尚未验证。
> `hybrid_rerank` 在接入 BGE-Reranker 前等价于 RRF，不能作为真实重排结果写论文。
> 图扩展是一跳种子图的**可选**能力；多跳分解、LangGraph 路由、PDF.js 高亮尚未接入默认链路（Phase 2b/3），
> 不要在当前论文结果中声称已完成。

## 技术栈（固定基线）

| 层 | 选型 |
|---|---|
| 前端 | Next.js + TypeScript + Tailwind CSS（当前为临时演示页） |
| PDF 展示 | PDF.js（待接入） |
| 后端 | FastAPI + Pydantic |
| 关系库 | PostgreSQL |
| 向量库 | Qdrant |
| 解析 | MinerU（当前 PyMuPDF 降级） |
| 切分 | 结构感知 + Parent-Child |
| Embedding | BGE-M3（当前 Hashing 占位） |
| 稀疏检索 | Qdrant BM25（应用侧权重 + IDF modifier） |
| 融合 | RRF |
| 重排 | BGE-Reranker-v2-m3（待接入） |
| 生成 | DeepSeek API（默认 mock） |
| 工作流 | LangGraph（后续） |
| 后台任务 | ARQ + Redis |
| 流式 | SSE |
| 文件 | 本地文件系统，按版本目录管理 |
| 评测 | 自建 JSONL 测试集 + 批量评测脚本；RAGAS 辅助（后续） |
| 部署 | Docker Compose（当前只起依赖服务） |

## 快速开始

```bash
docker compose -f infra/docker-compose.yml up -d

cd apps/api
cp .env.example .env
uv sync
uv run python ../../scripts/make_sample_pdf.py
uv run python ../../scripts/migrate_db.py
uv run uvicorn app.main:app --reload --port 8000
```

另开终端：

```bash
cd apps/api && uv run arq app.worker.WorkerSettings
```

打开 <http://127.0.0.1:8000>。上传资料 → 提问 → 点击 `[S1]` 跳到 PDF 页码；列表中可“更新版本”。

验收与评测：

```bash
cd apps/api
uv run python ../../scripts/smoke_test.py           # A/B/C，跑完清理
uv run python ../../scripts/smoke_test.py --keep    # 保留演示文档
uv run python ../../scripts/evaluate.py --dataset ../../eval/sample_questions.jsonl \
  --modes dense,bm25,hybrid,hybrid_rerank --out ../../eval/runs/demo
```

完整命令、API 示例与版本更新/回滚见 [开发说明](docs/development.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [技术方案（定稿）](docs/technical-plan.md) | 架构、数据模型、引用协议、实验设计、开发计划、验收清单 |
| [开发说明](docs/development.md) | 启动、API、代码结构、已知限制、下一阶段 |
| [ADR-0001 混合检索](docs/adr/0001-hybrid-retrieval.md) | 为什么是 Dense + BM25 + RRF |
| [ADR-0002 版本化索引](docs/adr/0002-versioned-index.md) | 为什么不依赖 PostgreSQL/Qdrant 跨库事务 |
| [ADR-0003 引用验证](docs/adr/0003-citation-validation.md) | 引用有效性、支持性、事实正确性的分层 |
| [增强架构与状态](docs/architecture-enhancement.md) | 12 项增强能力的实现状态、Phase 2/3 计划、论文口径边界 |
| [架构审计（2026-10-20）](docs/audit-2026-10-20.md) | 实际执行路径、模块完成度、差距与风险、下一阶段优先级 |
| [待定项](docs/open-items.md) | 数据来源、硬件、模板等尚未锁死的事项 |

## 仓库结构

```text
apps/api/
  app/
    api/          文档、问答、会话、健康检查
    ingestion/    解析、切分、Embedding、入库流水线
    retrieval/    BM25、Qdrant、RRF、Reranker、检索服务
    generation/   LLM 适配、引用解析、声明级检查、支持性验证
    query/        Typed Query IR、硬约束编译、确定性路由
    species.py    品种解析与识别
    migrations.py 轻量增量迁移
    models.py     13 张 PostgreSQL 表（含图/日志）
  tests/          单元测试
  pyproject.toml
infra/
  docker-compose.yml   Postgres + Qdrant + Redis
scripts/
  make_sample_pdf.py   生成演示用合成 PDF
  smoke_test.py        A/B/C 端到端验收
  evaluate.py          批量评测、导出 CSV/JSON
  migrate_db.py        建表 + 增量迁移
eval/
  sample_questions.jsonl  合成测试集（非论文 Ground Truth）
docs/
  adr/
data/             文档、解析产物、示例（不入库）
```

## 重要提醒

- 示例 PDF 是合成的演示资料，**不构成养殖或用药依据**。
- 当前版本没有认证，只适合本机开发。
- 当前迁移只支持加列；改列类型/删列前引入 Alembic。
- `eval/sample_questions.jsonl` 是合成数据，不能当作论文 Ground Truth。
- 进入论文实验前，必须把 Hash embedder 换成 BGE-M3，并固定模型快照与参数。