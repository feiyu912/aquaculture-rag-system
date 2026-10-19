# 水产养殖 RAG 知识问答系统

本科毕业设计项目：**《基于检索增强生成的水产养殖知识问答系统设计与实现》**

> 当前状态：**技术方案 v1.0 已定稿，开发尚未开始。**
> 方案基线见 [docs/technical-plan.md](docs/technical-plan.md)。方向性变更必须新增 ADR，不能直接在实现中悄悄改路线。

## 项目定位

面向水产养殖专业知识查询，构建一个可更新、可追溯、可评测的 RAG Web 系统：

- **混合检索**：BGE-M3 Dense + Qdrant BM25 → RRF → BGE-Reranker-v2-m3
- **知识更新**：文档与版本分离，版本化索引，激活后异步清理旧版本
- **可验证引用**：Source ID 映射、引用有效性校验、证据支持性评估、PDF 原文定位
- **轻量工作流**：LangGraph 只负责路由、必要重试和证据不足分支，不做无条件的多轮反思
- **可复现实验**：检索消融、回答质量、引用可靠性、系统性能四组实验

## 技术栈（固定基线）

| 层 | 选型 |
|---|---|
| 前端 | Next.js + TypeScript + Tailwind CSS |
| PDF 展示 | PDF.js |
| 后端 | FastAPI + Pydantic |
| 关系库 | PostgreSQL |
| 向量库 | Qdrant |
| 解析 | MinerU（保留适配接口） |
| 切分 | 结构感知 + Parent-Child |
| Embedding | BGE-M3 |
| 稀疏检索 | Qdrant BM25（`multilingual` 分词器） |
| 融合 | RRF |
| 重排 | BGE-Reranker-v2-m3 |
| 生成 | DeepSeek API |
| 工作流 | LangGraph（轻量） |
| 后台任务 | ARQ + Redis |
| 流式 | SSE |
| 文件 | 本地文件系统，按版本目录管理 |
| 评测 | 自建评测集 + RAGAS 辅助 |
| 部署 | Docker Compose |

## 文档

| 文档 | 内容 |
|---|---|
| [技术方案（定稿）](docs/technical-plan.md) | 架构、数据模型、引用协议、实验设计、开发计划、验收清单 |
| [ADR-0001 混合检索](docs/adr/0001-hybrid-retrieval.md) | 为什么是 Dense + BM25 + RRF，而不是 BGE-M3 Sparse 或 Elasticsearch |
| [ADR-0002 版本化索引](docs/adr/0002-versioned-index.md) | 为什么不依赖 PostgreSQL/Qdrant 跨库事务 |
| [ADR-0003 引用验证](docs/adr/0003-citation-validation.md) | 引用有效性、支持性、事实正确性的分层 |
| [待定项](docs/open-items.md) | 数据来源、硬件、模板等尚未锁死的事项 |

## 计划中的仓库结构

```text
apps/
  api/            FastAPI 应用、ARQ worker
  web/            Next.js 前端
packages/
  ingestion/      MinerU 适配、结构解析、切分
  retrieval/      Dense / BM25 / RRF / Reranker
  generation/     Prompt、引用解析、校验
  evaluation/     评测脚本与数据
docs/
  adr/
infra/
  docker-compose.yml
data/             本地文档与解析产物（不入库）
```

## 快速开始

开发环境尚未搭建。第一阶段先确认数据来源与样例 PDF，再按技术方案第 12 节的顺序推进。