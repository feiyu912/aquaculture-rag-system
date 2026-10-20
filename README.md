# 水产养殖 RAG 知识问答系统

本科毕业设计项目：**《基于检索增强生成的水产养殖知识问答系统设计与实现》**

> 当前状态：**技术方案 v1.0 已定稿；可运行纵向切片 + A/B/C 验收场景的关键补强已完成。**
> 方案基线见 [技术方案](docs/technical-plan.md)，启动方式见 [开发说明](docs/development.md)。
>
> **本机默认运行态（2026-10-20，不是论文实验态）**：Dense=`BAAI/bge-m3`（FlagEmbedding/MPS/fp16）；
> Reranker=`BAAI/bge-reranker-v2-m3`（本地权重）；LLM=`openai-compatible-model`（OpenAI 兼容网关，真实调用）；
> Parser=`PyMuPDF`；
> 前端=`apps/web`（Next.js 15 + TS + Tailwind v4 + shadcn/ui + Lucide，已接入真实接口；
> 旧的静态单页仍保留在 8000 端口）。当前索引为独立集合 `kb_chunks_bge_m3_v1`（6 个 active 文档、190 个向量点，含 3 份真实地方标准）。
> MinerU、LangGraph 尚未启用；PDF.js 已在文献阅读模块接入（含 CropBox 相对 bbox 高亮）。详见 [真实模型验证记录](docs/real-model-validation-2026-10-20.md)
> 与 [架构审计](docs/audit-2026-10-20.md)（后者是切换 BGE 前的历史快照）。

## 项目定位

面向水产养殖专业知识查询，构建一个可更新、可追溯、可评测的 RAG Web 系统：

- **混合检索（已接入）**：BGE-M3 Dense + Qdrant BM25 → RRF → BGE-Reranker-v2-m3（`hybrid_rerank` 为真实重排；`noop` 仅作消融）
- **知识更新**：文档与版本分离，版本化索引，激活后旧版本归档；软删除后异步清理派生向量，DB 行/原文件保留
- **可验证引用**：Source ID 映射、引用有效性校验、证据支持性评估、PDF 页码定位（bbox 高亮待接入）
- **轻量工作流（目标）**：LangGraph 负责路由、必要重试和证据不足分支（当前为确定性路由，无 LangGraph）
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
- **声明级引用检查（v0）**：句子级/带引用表格行 `[S1]` 映射与词面支持性；可选 BGE-M3 余弦筛选，不冒充 NLI
- **轻量领域图（可开关）**：人工审核种子实体/别名/关系、chunk mention、有界多跳扩展、Graph-to-Chunk
- **规则问题分解（可开关）**：多指标问题拆 facet 子查询，继承硬约束并参与 RRF
- **证据要求 + 定向补检（可开关）**：facet 缺口检查、最多一次补充检索
- **确定性自适应路由（可开关）**：计算/现行规范缺少工具或日期元数据时安全拒答
- **检索 Trace**：按 request_id 查看排名、证据、IR、gate 与耗时
- 108 个默认单元测试（另有 2 个 BGE 真模型集成测试，`RUN_BGE_TESTS=1` 时运行）+ A/B/C 冒烟测试 + 批量评测 CLI

> ⚠️ BGE-M3 与 BGE-Reranker 已真实加载并在本机索引上验证；`hybrid_rerank` 现在记录
> `reranker=BAAI/bge-reranker-v2-m3`，不再等价于 RRF。`noop` 仅保留为消融对照。
> PyMuPDF 仍是 MinerU 的临时解析器。OpenAI 兼容网关的真实 SSE 已跑通；原生 DeepSeek endpoint
> 未配置/未验证。Mock 仅用于离线回归，不得用于论文模型性能结论。
> 图扩展是有界多跳种子图的**可选**能力（默认 2 跳、可反向，带 path trace）；跨文档证据级多跳、LangGraph 路由尚未接入默认链路。
> 当前只有 6 个 active 文档（3 份真实标准），不足以宣称检索效果。

## 技术栈（固定基线）

| 层 | 选型 |
|---|---|
| 前端 | Next.js 15 + TypeScript + Tailwind CSS v4 + shadcn/ui + Lucide（`apps/web`，已接入真实接口） |
| PDF 展示 | PDF.js（已接入，含 CropBox 相对 bbox 精确高亮） |
| 后端 | FastAPI + Pydantic |
| 关系库 | PostgreSQL |
| 向量库 | Qdrant |
| 解析 | MinerU（当前 PyMuPDF 降级） |
| 切分 | 结构感知 + Parent-Child |
| Embedding | BGE-M3（已接入；FlagEmbedding/MPS） |
| 稀疏检索 | Qdrant BM25（应用侧权重 + IDF modifier） |
| 融合 | RRF |
| 重排 | BGE-Reranker-v2-m3（已接入；Noop 仅消融） |
| 生成 | OpenAI 兼容网关（`openai-compatible-model`，已验证）；原生 DeepSeek 待验证 |
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

再开一个终端启动 Web 前端：

```bash
cd apps/web
npm install
npm run dev          # http://127.0.0.1:3000
```

前端通过 `NEXT_PUBLIC_API_BASE_URL`（默认 `http://127.0.0.1:8000`）访问后端，
**不携带任何密钥**。四个模块：智能问答（`/chat`）、知识库（`/knowledge`）、
文献阅读（`/reader`，PDF.js 引用高亮）、检索调试（`/debug`）。
设计规范见 [前端设计系统](docs/design-system.md)。

验收与评测：

```bash
cd apps/api
uv run python ../../scripts/smoke_test.py           # A/B/C，跑完清理
uv run python ../../scripts/smoke_test.py --keep    # 保留演示文档
uv run python ../../scripts/evaluate.py --dataset ../../eval/sample_questions.jsonl \
  --modes dense,bm25,hybrid,hybrid_rerank --out ../../eval/runs/demo

# 真实三文档 70 题、chunk 级检索指标（结果见 docs/retrieval-evaluation-2026-10-20.md）
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run python ../../scripts/evaluate_retrieval_metrics.py \
  --query-ir --out ../../eval/runs/real_questions_v1_1_query_ir
```

完整命令、API 示例与版本更新/回滚见 [开发说明](docs/development.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [技术方案（定稿）](docs/technical-plan.md) | 架构、数据模型、引用协议、实验设计、开发计划、验收清单 |
| [开发说明](docs/development.md) | 启动、API、代码结构、已知限制、下一阶段 |
| [前端设计系统](docs/design-system.md) | 色彩/字体/间距/组件规范、布局规则、视觉回归检查 |
| [ADR-0001 混合检索](docs/adr/0001-hybrid-retrieval.md) | 为什么是 Dense + BM25 + RRF |
| [ADR-0002 版本化索引](docs/adr/0002-versioned-index.md) | 为什么不依赖 PostgreSQL/Qdrant 跨库事务 |
| [ADR-0003 引用验证](docs/adr/0003-citation-validation.md) | 引用有效性、支持性、事实正确性的分层 |
| [真实检索评测（2026-10-20）](docs/retrieval-evaluation-2026-10-20.md) | 70 题、Dense/BM25/Hybrid/Reranker 的 Recall/nDCG/MRR、失败分析与局限 |
| [增强架构与状态](docs/architecture-enhancement.md) | 12 项增强能力的实现状态、Phase 2/3 计划、论文口径边界 |
| [架构审计（2026-10-20）](docs/audit-2026-10-20.md) | 实际执行路径、模块完成度、差距与风险、下一阶段优先级 |
| [待定项](docs/open-items.md) | 数据来源、硬件、模板等尚未锁死的事项 |

## 仓库结构

```text
apps/
  api/                FastAPI 后端（RAG、SSE、知识库、引用、调试接口）
  web/                Next.js 前端（智能问答 / 知识库 / 文献阅读 / 检索调试）
infra/
  docker-compose.yml   Postgres + Qdrant + Redis
scripts/
  make_sample_pdf.py   生成演示用合成 PDF
  smoke_test.py        A/B/C 端到端验收
  evaluate.py          旧版批量评测、导出 CSV/JSON
  evaluate_retrieval_metrics.py  chunk 级真实检索指标
  build_real_eval_dataset.py     从 seed 解析真实 gold chunk
  migrate_db.py        建表 + 增量迁移
eval/
  sample_questions.jsonl  合成测试集（非论文 Ground Truth）
  real_questions_v1.*     70 条真实文档题（AI 辅助、待人工复核）
docs/
  adr/
  design-system.md     前端设计系统（色彩/字体/间距/组件/视觉回归）
data/             文档、解析产物、示例（不入库）
```

## 重要提醒

- 示例 PDF 是合成的演示资料，**不构成养殖或用药依据**。
- 当前版本没有认证，只适合本机开发。
- 当前迁移只支持加列；改列类型/删列前引入 Alembic。
- `eval/sample_questions.jsonl` 是合成数据，不能当作论文 Ground Truth。
- 进入论文实验前，必须固定 BGE-M3/BGE-Reranker 模型快照、设备、fp16 与集合 manifest；当前已有 70 条真实文档题（AI 辅助、待人工复核），仍不能替代人工 qrels。