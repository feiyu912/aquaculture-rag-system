# Aquaculture RAG 后端 API Contract

> 版本：2026-10-20（rev. 2026-10-20b）
> 依据：`apps/api` 当前真实代码与 `GET /openapi.json`，不是设计稿；`apps/api/tests/test_api_contract.py` 固定 18 个已挂载路由。
> 面向：Qoder 的 Next.js 前端。前端只依赖本文列出的接口；未列出的路径不要假设存在。
> Base URL（本地）：`http://127.0.0.1:8000`
> 所有业务接口前缀：`/api`；日期时间均为 UTC ISO-8601（例如 `2026-10-20T02:44:51.257558Z`）。

## 1. 通用约定

### 1.1 认证与 CORS

当前是本地开发版，**没有认证/鉴权**。不要在前端硬编码任何 API Key；LLM Key 只在后端 `.env`。

CORS 配置（`app/main.py`）实际为：

```text
Access-Control-Allow-Origin: *
Allow-Credentials: false
Allow-Methods: *
Allow-Headers: *
```

因此浏览器可以直接跨域访问，但不能携带 cookie 凭据。正式部署时必须收紧。

### 1.2 请求与响应格式

- 普通接口：`application/json; charset=utf-8`。
- 上传：`multipart/form-data`。
- 聊天：`POST /api/chat/stream`，响应 `text/event-stream`。
- UUID 均为标准 36 字符 UUID 字符串。
- 错误响应默认为 FastAPI 形状：

```json
{"detail": "中文错误信息"}
```

或 `detail` 为对象：

```json
{
  "detail": {
    "message": "相同内容的文件已存在",
    "document_id": "…",
    "version_id": "…"
  }
}
```

- 请求体校验失败为 HTTP 422，形状：

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "question"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

### 1.3 主要 HTTP 状态码

| 状态 | 含义 | 典型场景 |
|---|---|---|
| 200 | 成功 | 查询、列表、回滚、验证 |
| 201 | 创建成功 | 创建会话 |
| 202 | 已接受 | 上传/新版本已入队 |
| 204 | 成功无 body | 删除会话/文档 |
| 400 | 业务参数错误 | 空问题、非法品种、非法年份 |
| 404 | 资源不存在 | 文档/版本/任务/会话/消息/引用/trace |
| 409 | 状态冲突 | 重复 PDF、版本未就绪、不可回滚、不可重试 |
| 413 | 文件过大 | 超过 `MAX_UPLOAD_MB`（默认 100） |
| 415 | 文件类型错误 | 非 PDF 扩展名、非 PDF 魔数、非法 MIME |
| 422 | Pydantic 校验失败 | 字段缺失、类型/长度错误 |
| 503 | 依赖不可用 | Qdrant/检索失败、LLM 未配置、Redis/ARQ 不可用 |

## 2. 聊天与会话

### 2.1 创建会话

```http
POST /api/sessions
```

无请求体。成功 `201`：

```json
{
  "id": "6f1f5d8e-3f6a-4c2b-9d7e-2a1b3c4d5e6f",
  "title": "新会话",
  "created_at": "2026-10-20T02:00:00.000000Z",
  "last_message_at": null
}
```

聊天请求如果传 `session_id`，会话必须存在，否则 404；如果不传，后端自动创建会话，标题取问题前 30 字符。

### 2.2 会话列表

```http
GET /api/sessions
```

返回最多 100 个会话，按 `updated_at` 倒序。`SessionOut` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 会话 ID |
| title | string | 标题 |
| created_at | datetime | 创建时间 |
| last_message_at | datetime/null | 最近消息时间 |

### 2.3 会话消息

```http
GET /api/sessions/{session_id}/messages
```

成功返回 `MessageOut[]`，按 `created_at` 升序。`MessageOut`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 消息 ID |
| role | `user`/`assistant` | 角色 |
| content | string | 正文；流式期间可能为空 |
| status | string | `completed` / `streaming` / `failed` |
| created_at | datetime | 创建时间 |
| citations | CitationOut[] | 助手消息的引用 |
| model | string/null | 实际生成模型名 |
| latency_ms | int/null | 总延迟 |
| meta | object | 包含 `request_id`、`citation_check`、`superseded`、`llm_planner` 等 |

错误：会话不存在 404。

### 2.4 删除会话

```http
DELETE /api/sessions/{session_id}
```

成功 `204`，无 body。删除会话会级联删除消息和引用（数据库关系定义）。不存在 404。

### 2.5 聊天流式请求

```http
POST /api/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

请求体：

```json
{
  "question": "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？",
  "session_id": "6f1f5d8e-3f6a-4c2b-9d7e-2a1b3c4d5e6f",
  "category": null,
  "species": "中华绒螯蟹",
  "retrieval_mode": "hybrid_rerank",
  "answer_mode": "document_rag"
}
```

| 字段 | 必填 | 类型/枚举 | 说明 |
|---|---|---|---|
| question | 是 | string 1–2000 | 问题；前后空白会被去除 |
| session_id | 否 | UUID/null | 不传则新建会话 |
| category | 否 | string/null | 文档分类硬过滤，例如 `水质管理` |
| species | 否 | string/null | 品种硬过滤；建议只传单一品种 |
| retrieval_mode | 否 | `dense`/`bm25`/`hybrid`/`hybrid_rerank` | 默认 `hybrid` |
| answer_mode | 否 | `document_rag`/`document_faq_rag`/`faq_direct` | 默认 `document_rag`，见 2.4.1 |

#### 2.4.1 `answer_mode` 语义与错误码

| 值 | 行为 | 前置开关 |
|---|---|---|
| `document_rag` | 只用原始文献；FAQ 阶段**不发起**任何查询 | 无（默认） |
| `document_faq_rag` | 先用原文；原文证据不足时才追加已核验 FAQ（最多 2 条，不顶替原文） | `ENABLE_FAQ_RETRIEVAL=true` |
| `faq_direct` | 原文不足且单条已核验 FAQ 同时满足 5 个严格条件时，直接由 FAQ 作答；否则自动回退到 `document_faq_rag` | `ENABLE_FAQ_RETRIEVAL=true` **且** `ENABLE_FAQ_DIRECT_ANSWER=true` |

错误码：

| 情况 | 状态码 | detail |
|---|---|---|
| 请求了 `document_faq_rag` / `faq_direct` 但开关未开 | 400 | `FAQ 检索未启用，answer_mode 仅支持 document_rag` |
| 请求了 `faq_direct` 但直答开关未开 | 400 | `FAQ 直答未启用` |
| 枚举值非法 | 422 | pydantic `literal_error` |

`faq_direct` 的 5 个条件（任一不满足即回退，且**不会**降低充分性阈值）：已核验且支撑版本仍 active；dense 与 BM25 **同时排第一**；物种/阶段/地区不冲突；严格主题（用药、剂量、禁用、诊断）要求支撑为权威来源；答案不含"如果/视情况/分阶段"等条件句。

`status` 事件新增字段：`answer_mode`、`answer_mode_used`、`faq_supplement`（含 `accepted`/`rejected`/`skipped`）、`faq_direct`（含 `used`/`fallback_reason`）、`applicability_filter`、`strict_source_filter`。

注意：`hybrid_rerank` 会调用真实 BGE-Reranker，延迟高于 `hybrid`；不要在前端默认强制。

#### 2.5.1 为什么不用 EventSource

接口是 `POST` 且请求体是 JSON。浏览器原生 `EventSource` 只支持 GET，因此前端必须使用 `fetch()` + `ReadableStream` 解析 SSE，或用支持 POST SSE 的客户端。建议用 `AbortController` 支持取消。

#### 2.5.2 事件总览

服务端只在**检索成功且生成器可初始化**后才建立 SSE。事件顺序固定为：

```text
meta → status → sources → token* → citation_check → done
```

异常分支：

- 生成中抛错：`meta → status → sources → token* → error`（终止，无 `citation_check`/`done`）
- 模型无可见文本：`meta → status → sources → token* → error`（`empty_generation`）
- 检索失败/生成器未配置：**不会建立 SSE**，返回 HTTP 503；数据库里助手消息标记为 failed。
- 客户端中断：服务端在生成阶段捕获取消，把助手消息标记为 `failed`，`meta.error=client_disconnected`；连接已断，客户端收不到后续事件。

每个 SSE block 的格式：

```text
event: <event-name>
data: <单行 JSON>

```

`data` 是单行 JSON（中文不转义）。没有 `id:`、没有 heartbeat、没有 `retry:`；不要依赖断线自动重连。

#### 2.5.3 `meta`

```json
{
  "request_id": "ddfb6e1483c04abaa1ec489963684eb8",
  "session_id": "6f1f5d8e-3f6a-4c2b-9d7e-2a1b3c4d5e6f",
  "message_id": "0a65195e-5c4a-4418-b19c-c1250806e3bd"
}
```

`request_id` 用于 `GET /api/debug/query-logs/{request_id}`。`message_id` 用于消息级验证和前端占位。

#### 2.5.4 `status`

```json
{
  "stage": "retrieved",
  "sources": 5,
  "active_versions": 5,
  "sufficient": true,
  "retrieval_mode": "hybrid_rerank",
  "species_filter": "中华绒螯蟹",
  "query_ir": { "...": "见 QueryIR" },
  "adaptive_route": "simple",
  "targeted_retrieval": null,
  "graph_expansion": null,
  "llm_planner": null,
  "gate": { "...": "见 EvidenceGate" }
}
```

- `sufficient=false` 时 `sources` 通常为 `[]`，但事件仍会发送。
- `llm_planner` 在规则模式为 `null`；开启后包含 `used_llm`、`error`、`attempts`、`plan`、`subquestions`、`tasks`、`constraints`、`assumptions`。单 facet 事实问题会被跳过并带 `skipped=simple_rule_ir`，以避免不必要的模型延迟。
- `query_ir` 可能为 `null`（Query IR 关闭时）。

#### 2.5.5 `sources`

```json
{
  "sources": [
    {
      "source_id": "S1",
      "index": 1,
      "document_id": "3f534c05-99c9-493e-9e18-323f9ee9a3c1",
      "version_id": "2b5511ca-7886-4e40-964e-5a069da06694",
      "version_no": 1,
      "chunk_id": "65edfb85-bfc0-51e6-baf5-75467bba628b",
      "child_chunk_id": "e25f6ae4-dc20-52b3-aae6-9f9c8601ce36",
      "title": "DB36_T 2225—2026 中华绒螯蟹池塘培育扣蟹技术规程",
      "species": ["中华绒螯蟹"],
      "page": 7,
      "quote": "8.1水质指标溶氧量5mg/L以上，pH值7.5~8.5，透明度30cm~50cm，氨氮低于0.5mg/L，亚硝酸盐低于0.05mg/L。",
      "heading_path": ["中华绒螯蟹池塘培育扣蟹技术规程", "8.1水质指标"],
      "graph_provenance": null,
      "location": {
        "page": 7,
        "bbox": [70.92, 170.01, 543.85, 213.39],
        "coordinate_system": "pdf_points",
        "origin": "bottom-left",
        "rotation": 0,
        "page_width": 595.3,
        "page_height": 841.9
      },
      "bbox": [70.92, 170.01, 543.85, 213.39],
      "coordinate_system": "pdf_points",
      "origin": "bottom-left",
      "rotation": 0,
      "page_width": 595.3,
      "page_height": 841.9
    }
  ]
}
```

Source 字段说明：

| 字段 | 说明 |
|---|---|
| source_id | `S1`…；与回答中 `[S1]` 一一对应 |
| index | 整数 1…；等价于 source_id 数字 |
| document_id | 逻辑文档 ID，用于文档详情/删除 |
| version_id | 该引用对应的精确版本 ID，**PDF 定位必须用这个** |
| version_no | 版本号 |
| chunk_id | 父块（用于引用存储/定位） |
| child_chunk_id | 实际命中的子块 |
| page | 1-based PDF 页码 |
| quote | 展示给用户并用于引用的原文片段 |
| heading_path | 标题路径，可能为空 |
| graph_provenance | 仅图谱命中的 source 非空：`matched_entities`、`paths`、`mention_count`、`seed_terms`；普通向量命中为 `null` |
| location | 规范坐标对象 |
| bbox | `[x0,y0,x1,y1]`，PDF points，**左下角原点** |
| coordinate_system | 当前固定 `pdf_points` |
| origin | 当前固定 `bottom-left` |
| rotation | 页面旋转角 |
| page_width/page_height | 页面尺寸（PDF points） |

**PDF.js 坐标转换**：`bbox` 是 PDF 左下原点坐标；PDF.js viewport 通常使用左上原点，渲染时使用：

```ts
const [x0, y0, x1, y1] = source.bbox;
const rect = {
  left: x0,
  top: source.page_height - y1,
  width: x1 - x0,
  height: y1 - y0,
};
// 再按 viewport.scale 缩放
```

若 `location`/`bbox` 为 `null`，只能退化为页码跳转。

#### 2.5.6 `token`

```json
{"text": "扣蟹池塘培育的"}
```

可能 0 个或多个。前端应逐块追加，不要按完整句子假设。

#### 2.5.7 `citation_check`

```json
{
  "cited_indices": [5, 3, 1, 4],
  "invalid_indices": [],
  "cited_factual": 3,
  "factual_sentences": 4,
  "coverage": 0.75,
  "valid": true,
  "claims": [
    {
      "claim": "扣蟹池塘培育的水质指标要求溶氧量保持在 5 mg/L 以上 [S5]。",
      "cited_indices": [5],
      "status": "weak",
      "score": 0.4,
      "method": "lexical_overlap_v0",
      "matched_terms": ["以上", "指标", "水质", "溶氧量"]
    }
  ],
  "claim_summary": {
    "total": 7,
    "supported": 3,
    "weak": 1,
    "unverified": 1,
    "uncited": 1,
    "support_rate": 0.429,
    "method": "lexical_overlap_v0"
  }
}
```

- `valid` 只表示引用编号存在且在范围内，**不表示事实正确**。
- `coverage` 是“有引用的事实句/事实句”比例，不是正确率。
- `claim_summary.support_rate` 是词面支持率，**不是 NLI/事实准确率**；默认论文口径必须标注 `lexical_overlap_v0`。
- `claims` 仅在 `ENABLE_CLAIM_VERIFICATION=true` 时出现（默认 true）。
- `ENABLE_SEMANTIC_CLAIMS=true`（默认 false）时，SSE 的 claim 额外可能含 `lexical_status`、`semantic_score`、`semantic_index`；`method` 可能为 `bge_m3_cosine_v0`，`claim_summary.method` 为 `lexical_overlap_v0+bge_m3_cosine_v0`。这只是 BGE-M3 余弦相似度筛选，**不是 NLI，也不是事实正确性**。
- `POST /api/messages/{message_id}/verify-claims` 仍只做词面校验；语义开关目前只影响 SSE 生成后的 claim report。

#### 2.5.8 `done`

```json
{
  "message_id": "0a65195e-5c4a-4418-b19c-c1250806e3bd",
  "model": "openai-compatible-model",
  "usage": {"prompt_tokens": 1383, "completion_tokens": 400},
  "cost_usd": 0.0,
  "timings": {
    "dense_ms": 71.2,
    "sparse_ms": 5.6,
    "graph_ms": 0.0,
    "retrieval_ms": 3099.0,
    "ttft_ms": 7072.2,
    "generation_ms": 3780.4,
    "total_ms": 10852.7
  },
  "retrieval_mode": "hybrid_rerank",
  "query_ir": {"...": "..."},
  "adaptive_route": "simple",
  "targeted_retrieval": null,
  "graph_expansion": null,
  "llm_planner": null,
  "sufficient": true,
  "gate": {"...": "..."},
  "citation_check": {"...": "..."}
}
```

`cost_usd` 仅在配置了价格时非零；当前通用 OpenAI 兼容网关没有价格配置，因此可能为 0，不能把 0 当免费证据。

#### 2.5.9 `graph_expansion`

`GRAPH_EXPANSION=true` 时，`status`/`done` 的 `graph_expansion` 是结构化检索路径，不是最终事实：

```json
{
  "seed_entity_ids": ["..."],
  "expanded_entity_ids": ["..."],
  "seed_terms": ["浮头"],
  "expanded_terms": ["增氧", "水质", "溶解氧"],
  "max_hops": 2,
  "bidirectional": true,
  "relation_trace": [
    {
      "source": "浮头",
      "target": "溶解氧",
      "relation_type": "ASSOCIATED_WITH",
      "direction": "forward",
      "hop": 1,
      "path": ["浮头", "溶解氧"],
      "path_entity_ids": ["...", "..."],
      "provenance_version_id": "3f534c05-99c9-493e-9e18-323f9ee9a3c1",
      "confidence": 0.9
    },
    {
      "source": "溶解氧",
      "target": "增氧",
      "relation_type": "MANAGEMENT_FOR",
      "direction": "reverse",
      "hop": 2,
      "path": ["浮头", "溶解氧", "增氧"],
      "path_entity_ids": ["...", "...", "..."]
    }
  ]
}
```

- 只遍历 `review_status=verified` 的关系；图谱默认关闭。
- `hop` 从 1 开始；`direction=reverse` 表示从关系的 target 反向走到 source。
- `provenance_version_id`/`confidence` 是该条边的来源文档版本与抽取置信度（边级 provenance）；
  某条 source 是经由图谱召回时，其 `graph_provenance.paths` 给出到达该 chunk 的实体路径。
- `max_hops` 默认 2，`graph_max_related` 默认 12，防止扩展爆炸。
- 图谱扩展只帮助召回候选 chunk，**不等于证据充分**；仍必须经过 `gate` 和引用校验。

#### 2.5.9a `targeted_retrieval`

`ENABLE_TARGETED_RETRIEVAL=true`（默认）且首轮 gate 不通过时，按“未覆盖的 evidence
requirement”逐条补检索；每次补检索都重新走同一 gate，阈值不变：

```json
{
  "mode": "requirement_targeted",
  "insufficient_reason": "missing_requirements",
  "targets": [
    {
      "requirement": "water:0",
      "label": "水质指标",
      "terms": ["盐度"],
      "supplement": "…原问题… 盐度",
      "second_sufficient": false,
      "second_gate_reason": "weak_overlap",
      "added_sources": 0
    }
  ],
  "sufficient_before": false,
  "sufficient_after": false
}
```

- 上限 `MAX_TARGETED_RETRIEVAL=2`；每次只补一个 requirement，避免一条稀释查询。
- `no_query_terms` / `no_evidence` / `current_regulation_unverified` /
  `list_completeness_unverified` 直接跳过补检索（清单完整性不是补检索能解决的）。
- `sufficient_after=false` 时最终 `sources=[]`；补检索不会放宽阈值，也不会把弱证据放进回答。

#### 2.5.10 `error`

```json
{
  "code": "generation_failed",
  "message": "…",
  "retryable": true
}
```

已知 `code`：

| code | 触发 | 是否已持久化失败 |
|---|---|---|
| `generation_failed` | 外部模型流式请求异常 | 是，助手消息 `failed` |
| `empty_generation` | 模型 200 但没有可见文本（常见于 reasoning 模型把 token 全用在思考） | 是，助手消息 `failed` |

`error` 是终止事件，不会再有 `citation_check` 或 `done`。HTTP 状态此时已经是 200（SSE 已开始），前端必须按事件处理，不能只看 HTTP status。

## 3. 引用对象（持久化读取）

`GET /api/sessions/{session_id}/messages` 中的 `CitationOut`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 引用行 ID，用于 `/api/citations/{id}/verify` |
| source_index | int | 对应 `[S1]` |
| document_id | UUID | 文档 |
| document_version_id | UUID | 精确版本 |
| chunk_id | UUID/null | 父块 |
| quote | string | 引用原文 |
| page | int/null | 页码 |
| bbox | object/array/null | **历史兼容字段**：旧行存的是完整 location 对象；新前端请优先读 `location` |
| location | object/null | 规范 location，结构同 SSE `location` |
| score | float/null | 检索/重排分数 |
| support_status | `unverified`/`supported`/`weak`/`unverified` | 声明支持状态；初始 `unverified` |
| support_score | float/null | 支持分数 |
| title | string/null | 反规范化标题，便于历史消息展示 |
| version_no | int/null | 版本号 |
| species | string[] | 文档品种 |

**重要**：`ChatCitation.bbox` 数据库列保存的是完整 `location` 对象，不是单纯的四元数组；API 新加了 `location` 字段来消除歧义。Qoder 应读 `location.bbox`，不要假设 `citation.bbox` 是数组。

### 3.1 单引用支持性验证

```http
POST /api/citations/{citation_id}/verify
Content-Type: application/json

{"claim": "溶氧量应保持在 5 mg/L 以上。"}
```

成功：

```json
{
  "citation_id": "e47473d6-1254-4066-9bd5-523860440014",
  "status": "supported",
  "score": 0.8,
  "method": "lexical_overlap_v0",
  "matched_terms": ["5", "mg", "以上", "溶解氧"]
}
```

- 该方法会写回 `support_status`/`support_score`。
- 当前默认是词面重叠，不是语义蕴含；不要展示为“事实已核实”。可选的 `bge_m3_cosine_v0` 也只是相似度筛选，不是 NLI。

### 3.2 消息级声明验证

```http
POST /api/messages/{message_id}/verify-claims
```

无请求体。返回：

```json
{
  "message_id": "0a65195e-5c4a-4418-b19c-c1250806e3bd",
  "summary": {"total": 7, "supported": 3, "weak": 1, "unverified": 1, "uncited": 1, "support_rate": 0.429, "method": "lexical_overlap_v0"},
  "claims": [{"claim": "…", "cited_indices": [5], "status": "weak", "score": 0.4, "method": "lexical_overlap_v0", "matched_terms": ["…"]}]
}
```

404：消息不存在。

## 4. 文档与版本

### 4.1 上传文档

```http
POST /api/documents
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| file | 是 | PDF；扩展名 `.pdf`，MIME 允许 `application/pdf`、`application/octet-stream`、`binary/octet-stream`；必须 `%PDF` 开头 |
| title | 否 | 文档标题；缺省用文件名 stem |
| category | 否 | 默认 `未分类` |
| species | 否 | 品种，支持 `,` `，` `、` `;` `/` `|` 分隔；空表示 `通用` |
| source_org | 否 | 来源机构 |
| source_url | 否 | 来源 URL |
| publish_year | 否 | 1900–2100 |
| document_status | 否 | 建议值：`formal`/`draft`/`popular`；写入 metadata，不改变文档 `status` |
| region | 否 | 适用地区，写入 metadata |

成功 `202`：

```json
{
  "document_id": "3f534c05-99c9-493e-9e18-323f9ee9a3c1",
  "version_id": "2b5511ca-7886-4e40-964e-5a069da06694",
  "job_id": "1db10ac8-0a70-460c-9d55-8c33852e8f93",
  "status": "queued"
}
```

错误：

- 409 重复内容：`detail` 含 `message`/`document_id`/`version_id`
- 413 文件过大
- 415 非 PDF
- 400 品种非法/年份非法/空文件
- 503 Redis/ARQ 不可用或入队失败（此时文档/任务可能已落库并标记 failed；用返回信息排查）

### 4.2 追加新版本

```http
POST /api/documents/{document_id}/versions
Content-Type: multipart/form-data
```

唯一表单字段：`file`（PDF）。版本号在文档级串行分配；成功 `202`，返回新的 `version_id`/`job_id`。

- 409：该文档已存在相同内容版本，`detail.version_id` 指向旧版本
- 404：文档不存在/已删除
- 415/413/503 同上

### 4.3 文档列表

```http
GET /api/documents?q=&status=&limit=100&offset=0
```

| 参数 | 默认 | 说明 |
|---|---|---|
| q | 空 | 标题模糊搜索（SQL `ILIKE`） |
| status | 空 | 按文档状态过滤，通常 `active`；已删除永不返回 |
| limit | 100 | 1–500 |
| offset | 0 | ≥0 |

返回 `DocumentOut[]`，按 `created_at` 倒序：

```json
{
  "id": "3f534c05-99c9-493e-9e18-323f9ee9a3c1",
  "title": "DB36_T 2225—2026 中华绒螯蟹池塘培育扣蟹技术规程",
  "category": "养殖技术",
  "species": ["中华绒螯蟹"],
  "status": "active",
  "current_version_id": "2b5511ca-7886-4e40-964e-5a069da06694",
  "current_version_no": 1,
  "page_count": 9,
  "created_at": "2026-10-20T02:10:48.037934Z",
  "source_org": null,
  "source_url": null,
  "publish_year": null,
  "document_status": null,
  "region": null
}
```

`status` 是文档生命周期（`active`/`deleted` 等）；`document_status` 是资料来源状态（正式/征求意见稿/科普），两者不同。不要混淆。

### 4.4 文档详情

```http
GET /api/documents/{document_id}
```

返回 `DocumentOut` 全部字段 + `versions`：

```json
{
  "...": "DocumentOut",
  "versions": [
    {
      "id": "2b5511ca-7886-4e40-964e-5a069da06694",
      "version_no": 1,
      "status": "ready",
      "page_count": 9,
      "content_hash": "…",
      "error_message": null,
      "created_at": "2026-10-20T02:10:48.037934Z",
      "activated_at": "2026-10-20T02:11:02.000000Z"
    }
  ]
}
```

版本 `status` 可能：`processing` / `ready` / `archived` / `failed`。只有 `ready` 的当前版本应被引用；历史 `archived` 版本可用于回滚。

404：文档不存在或已删除。

### 4.5 回滚版本

```http
POST /api/documents/{document_id}/rollback
Content-Type: application/json

{"version_id": "2b5511ca-7886-4e40-964e-5a069da06694"}
```

成功 `200` 返回更新后的 `DocumentOut`。

- 404：文档/版本不存在
- 409：版本未成功入库，或 Qdrant 中该版本向量已被清理
- 若目标已是当前版本，直接返回 200，不报错

### 4.6 删除文档（软删除）

```http
DELETE /api/documents/{document_id}
```

成功 `204`。行为：

- 文档 `status=deleted`，`current_version_id=null`
- 非 failed 版本变为 `archived`
- 排队/运行中的任务变为 `cancelled`
- **不立即删除 Qdrant 向量**；删除成功后 best-effort 向 ARQ 入队 `cleanup_deleted_vectors`，由 worker 清理孤儿 points 并刷新 manifest 的 active 文档/点数。
- Redis/ARQ 不可用时删除仍返回 `204`（向量清理不阻塞软删除）；可运行 `scripts/purge_deleted_vectors.py --apply` 兜底，默认 dry-run。
- 已删除文档不再出现在列表/详情/文件接口；历史引用仍可读消息

404：不存在。

### 4.7 物种列表

```http
GET /api/species
```

返回去重后的品种数组，`通用` 固定第一：

```json
["通用", "凡纳滨对虾", "中华绒螯蟹"]
```

## 5. 解析任务

### 5.1 查询任务

```http
GET /api/jobs/{job_id}
```

```json
{
  "id": "1db10ac8-0a70-460c-9d55-8c33852e8f93",
  "document_version_id": "2b5511ca-7886-4e40-964e-5a069da06694",
  "status": "succeeded",
  "progress": 100,
  "current_stage": "done",
  "error_code": null,
  "error_message": null,
  "metrics": {
    "page_count": 9,
    "chunks": 43,
    "children": 34,
    "dense_dim": 1024,
    "elapsed_ms": 12345.6
  }
}
```

状态：`queued` / `running` / `succeeded` / `failed` / `cancelled`。
阶段：`queued` / `parse` / `chunk` / `graph` / `embed` / `upsert` / `activate` / `done` / `cancelled`（具体阶段以任务实际值为准）。

404：任务不存在。

### 5.2 重试失败任务

```http
POST /api/jobs/{job_id}/retry
```

成功 `202` 返回 `JobOut`。仅 `failed`/`cancelled` 可重试，否则 409；队列不可用 503；版本/任务不存在 404。

## 6. PDF 原文件与引用定位

```http
GET /api/documents/{document_id}/file?version_id={version_id}
```

- `version_id` 可选；不传时使用当前版本。
- 成功返回 `application/pdf`，`Content-Disposition: inline; filename="<title>.pdf"`。
- 404：文档不存在/已删除、版本不存在、文件丢失。
- 前端用 `sources[].version_id` 或 `CitationOut.document_version_id` 作为参数，确保引用版本与页面一致。
- 当前 `FileResponse` 支持单段 `Range: bytes=...`：返回 `206 Partial Content`、`Accept-Ranges: bytes`、`Content-Range`，并带 `ETag`/`Last-Modified`；PDF.js 可以按 Range 加载，不需要先下载整文件。
- 需要认证时再补；当前本地无鉴权。

### 6.1 文档的引用历史

```http
GET /api/documents/{document_id}/citations?limit=50
```

- 返回该文档在历史回答中被引用过的全部记录，按引用时间倒序。
- `limit` 默认 50，最大 200。
- 每条记录在 `CitationOut` 基础上追加：`message_id`、`session_id`、`question`（来源会话标题）、`answer_preview`、`cited_at`。
- 文献阅读器用它渲染「引用高亮」侧栏：点击一条即可跳到对应页码并高亮 bbox；`session_id` 可用于回到原始会话。
- 404：文档不存在或已删除。

## 7. Debug Trace 与统计

### 7.1 单请求 Trace

```http
GET /api/debug/query-logs/{request_id}
```

`request_id` 来自 SSE `meta` 或消息 `meta.request_id`。返回：

```json
{
  "request_id": "ddfb6e1483c04abaa1ec489963684eb8",
  "question": "…",
  "retrieval_config": {"...": "..."},
  "query_ir": {"...": "..."},
  "llm_planner": null,
  "active_versions": ["..."],
  "gate": {"...": "..."},
  "timings": {"retrieval_ms": 3099.0, "total_ms": 10852.7},
  "rankings": {"dense": ["..."], "sparse": ["..."], "graph": []},
  "fused": ["..."],
  "fused_count": 20,
  "evidence": [{"source_id": "S1", "...": "..."}],
  "citation_check": {"...": "..."},
  "model": "openai-compatible-model",
  "cost_usd": 0.0
}
```

`rankings` 不返回完整 `fused` 列表，只返回各路排名和 `fused_count`；`evidence` 是持久化的 source 快照。404 表示无此 trace。

### 7.2 聚合统计

```http
GET /api/debug/stats?hours=24&limit=1000
```

| 参数 | 默认 | 范围 |
|---|---|---|
| hours | 24 | 1–720 |
| limit | 1000 | 1–5000 |

返回（不含问题/答案原文）：

```json
{
  "window_hours": 24,
  "queries": 136,
  "refusals": 25,
  "refusal_rate": 0.184,
  "routes": {"rag": 102, "simple": 34},
  "models": {"openai-compatible-model": 12, "mock": 124},
  "avg_retrieval_ms": 206.0,
  "p95_retrieval_ms": 741.6,
  "avg_total_ms": 1393.3,
  "p95_total_ms": 9566.8,
  "prompt_tokens": 55302,
  "completion_tokens": 20142,
  "cost_usd": 0.0
}
```

用途：Qoder 的检索可视化/运营面板。需要逐条明细时用 `/api/debug/query-logs/{request_id}`。

## 8. 健康检查

```http
GET /api/health
```

```json
{
  "status": "ok",
  "components": {"postgres": "ok", "qdrant": "ok", "redis": "ok"},
  "collection": "kb_chunks_bge_m3_v1",
  "llm_provider": "openai_compatible",
  "llm_configured": true,
  "embedding_model": "BAAI/bge-m3",
  "embedding_device": "mps",
  "reranker_model": "BAAI/bge-reranker-v2-m3",
  "max_sources": 5,
  "rerank_top_k": 8
}
```

- `status=ok` 仅当三个组件都 ok；否则 `degraded`。
- `llm_configured` 只检查配置字段是否存在，**不发起付费调用**；真正可用性要看一次聊天或 `/scripts/check_llm.py`。
- `max_sources` / `rerank_top_k` 是当前检索配置上限，前端应据此显示“最多 N 条来源”，不要把它当成固定返回条数；实际 `sources` 数量还受证据和 gate 约束。
- 该接口不返回 key、数据库 URL 等敏感信息。

## 9. QueryIR / Planner / Gate 可读结构

前端可以展示但不应据此做业务判断。`status.query_ir` 主要字段：

| 字段 | 说明 |
|---|---|
| original_question | 原始问题 |
| normalized_question | 术语归一化后的检索问题 |
| intent | `fact` / `complex` / `regulation` / `calculation` |
| strategy | `simple` / `semantic_expansion` / `multi_hop` / `regulation` / `calculation` |
| species / species_filter | 识别品种；只有唯一可信品种才进 filter |
| growth_stage / water_parameters / diseases | 领域 facet |
| requested_year / requires_current_regulation | 年份/现行规范需求 |
| unsupported_constraints | 未实现、不得硬过滤的约束 |
| warnings / confidence | 规则校验告警/置信度 |
| planner_source | `rules` / `llm` |
| planner_confidence | LLM 计划置信度 |
| planner_assumptions | 模型推断但未确认的假设 |
| planner_constraints | 每条约束的 `source`/`strength`/`accepted_as_hard`/`filter_applied`/`scope` |
| planner_subquestions | 规划出的子问题文本（向后兼容） |
| planner_tasks | 结构化检索任务：`question`/`facet`/`inherits`/`inherited_constraints`/`applicable_constraints`/`effective_query`/`soft_constraints`/`unverified_species_in_text` |
| rewritten_query | 保留原意的检索改写（可为空） |

`status.llm_planner`：

```json
{
  "enabled": true,
  "used_llm": true,
  "error": null,
  "duration_ms": 30927.4,
  "attempts": 1,
  "plan": {"intent": "complex", "...": "..."},
  "original_question": "…",
  "hard_filter": "中华绒螯蟹",
  "subquestions": ["..."],
  "tasks": [
    {
      "question": "…",
      "facet": "水质",
      "inherits": ["species", "growth_stage"],
      "inherited_constraints": {"species": ["中华绒螯蟹"]},
      "applicable_constraints": {"species": ["中华绒螯蟹"], "growth_stage": ["扣蟹培育"]},
      "effective_query": "中华绒螯蟹 扣蟹培育 …",
      "soft_constraints": [],
      "source": "llm"
    }
  ],
  "constraints": [],
  "assumptions": []
}
```

安全边界（前端文案必须一致）：

- LLM 推断的品种/约束默认是 **soft**，不会成为未经验证的硬过滤。
- `accepted_as_hard` 只表示通过校验；`filter_applied=true` 才表示该约束真的进入了 Qdrant 过滤。
- `scope` 取 `document_filter` / `retrieval_requirement` / `soft_context`；目前真正用于 Qdrant 硬过滤的仍只有文档级 `species_filter` 和请求显式 `category`。
- `planner_source=llm` 不等于“IR 一定正确”；失败会安全回退 `rules`，并在 `error` 中记录。
- `planner_tasks[].effective_query` 是子问题实际送入统一 Retrieval Engine 的检索文本；`inherited_constraints` 只记录被自动补入的字段，子问题原文已包含的字段不会重复拼接，避免把同义阶段/指标错误扩展成兄弟值。
- 仅实现文档级 `species_filter`（以及请求显式 `category`）的硬过滤；模型声称的其它 hard 约束会被降级为 `soft_context` 并写 warning `llm_constraint_not_implemented_as_hard`。
- 规则 IR 与 LLM IR 的对照评测见后续 `eval/`，当前不能宣称 LLM 一定更优。

## 10. 前端必须处理的异常

1. **HTTP 503 且无 SSE**：检索/LLM/队列不可用；显示“服务暂不可用”，不要显示“资料不足”。
2. **HTTP 200 后 `error` 事件**：生成失败；保留已收到 token，消息标记失败；可提示重试。
3. **`empty_generation`**：模型只输出了 reasoning、没有可见答案；提示重试或检查模型配置，不要显示空回答。
4. **`sufficient=false` 且 `sources=[]`**：证据不足，不展示引用；不要把它当作系统错误。
5. **`citation_check.valid=false`**：回答引用了不存在的 source；前端应显著提示，不要静默去掉标记。
6. **`citation_check.coverage<1`**：并非所有事实句都有引用；展示覆盖率，不要宣称“全部有据”。
7. **`claims[].status=weak/unverified/uncited`**：词面支持不足；不能显示“已核实/事实正确”。
8. **上传 409**：后端返回已存在文档/版本；前端应提示并跳到已有文档，不要重复上传。
9. **任务失败**：用 `GET /api/jobs/{id}` 看 `error_code`/`error_message`；`failed` 可调 retry，`cancelled` 只有在允许时重试。
10. **PDF 404**：文档已删除/版本丢失/文件缺失；引用仍保留文本，但无法定位，前端降级展示 quote。
11. **取消请求**：用 AbortController；取消后不要重连自动重发，避免重复计费。后端生成阶段会持久化 `client_disconnected`。
12. **CORS**：允许 `*` 但无 credentials；不要发送 cookie。

## 11. 当前未提供、前端不要假设的接口

以下能力尚未实现为独立 API，后续再补，不应在 Qoder 中臆造：

- 文档 chunk 列表/单 chunk 查询接口；
- 检索任务的独立“取消”接口（只有整请求 abort）；
- 用户认证、权限、租户；
- 文档批量上传/批量删除；
- 任务列表（只能按已知 `job_id` 查询）；
- 评测集/标注管理 API；
- SSE 心跳、断线重连、`Last-Event-ID`；
- 语义 NLI 支持性接口（当前只有词面 v0）。

## 13. 数据来源与 FAQ 复核接口（2026-10-21 新增）

本节接口对应"分层可信证据"改造。第一阶段 FAQ **不参与默认问答**：`enable_faq_retrieval` 默认 `false`，因此前端即使不调用本节接口，聊天行为也与之前一致。

### 13.1 `POST /api/documents/{document_id}/promote`

把 **staging** 文档发布为可检索文档，并把 `verification_status` 置为 `verified`。这是采集入库材料进入检索的唯一通道。

请求：

```json
{ "reviewer": "陶江", "note": "已核对原文与发布日期" }
```

约束与错误：

| 情况 | 状态码 | detail |
|---|---|---|
| 文档不存在或已删除 | 404 | `文档不存在` |
| 尚无 `current_version_id` | 409 | `文档尚未完成入库，无法发布` |
| 当前版本 `status != ready` | 409 | `当前版本未就绪，无法发布` |
| Qdrant 中该版本点位为 0 | 409 | `索引为空，请先重新入库` |

成功返回 `DocumentOut`（同 `GET /api/documents/{id}`）。重复调用是幂等的。

### 13.2 `GET /api/faq`

查询 FAQ 条目。查询参数：`review_status`（`pending`/`verified`/`rejected`）、`topic`、`limit`（1–100，默认 20）、`offset`。

响应数组元素：

```json
{
  "id": "uuid",
  "question": "…",
  "answer": "…",
  "species": ["中华绒螯蟹"],
  "topic": "水质",
  "source_dataset": "Mxode/Chinese-QA-AFAF",
  "source_authority": "unknown",
  "review_status": "pending",
  "usage_scope": "knowledge",
  "evidence_status": "supported",
  "quality_flags": ["drug_claim_needs_strict_source"],
  "supporting_count": 2,
  "reviewer": null,
  "reviewed_at": null,
  "indexed_at": null
}
```

### 13.3 `GET /api/faq/{faq_id}`

在 13.2 字段基础上追加 `supporting`（支撑 chunk 数组，含 `document_id`/`version_id`/`chunk_id`/`page`/`quote`/`authority`）、`review_notes`、`original_answer`。不存在返回 404。

### 13.4 `GET /api/faq/stats`

```json
{ "by_status": [{ "review_status": "pending", "evidence_status": "supported", "count": 68 }], "indexed": 0 }
```

### 13.5 `POST /api/faq/{faq_id}/review`

这是**唯一**能把 `review_status` 改成 `verified` 的接口。

请求：

```json
{ "action": "verify", "reviewer": "陶江", "answer": "可选：人工修订后的答案", "notes": "…" }
```

`action` 仅接受 `verify` / `reject`。

核验前置条件（不满足则拒绝）：

| 情况 | 状态码 | detail |
|---|---|---|
| `usage_scope = "eval"` | 409 | `评测专用条目（usage_scope=eval）不得进入知识库` |
| 已核验过 | 409 | `该条目已通过复核` |
| 无仍然 active 的支撑版本 | 422 | `缺少仍处于 active 状态的支撑文献，无法核验。…` |
| `evidence_status != "supported"` | 422 | `证据链状态为 none，不足以核验` |

`verify` 成功后：写入 `reviewer`/`reviewed_at`/`review_notes`，替换为人工修订答案（原答案保存在 `original_answer`），随后才写入 Qdrant，并回填 `indexed_at`。`reject` 会把条目从 Qdrant 删除。

> 前端注意：本接口不做鉴权，`reviewer` 只是审计字段，不是身份凭证。

### 13.6 `GET /api/data/sources`

返回 `data/sources/registry.yaml` 的源清单及入库统计：

```json
{
  "total": 22,
  "by_authority": { "official_technical": 9, "peer_reviewed": 12, "standard_draft": 1 },
  "by_policy": { "auto": 22 },
  "items": [
    { "id": "nftec-disease-2026-10", "url": "…", "authority": "official_technical",
      "resolver": "direct", "license": null, "documents_active": 0,
      "documents_staging": 1, "chunks": 21 }
  ]
}
```

### 13.7 `GET /api/data/runs`

采集/导入审计记录，参数 `kind`（`crawl`/`faq_import`/`index`）、`limit`。

### 13.8 `DocumentOut` 新增字段

| 字段 | 说明 |
|---|---|
| `source_type` | `pdf` / `html`（历史值 `web` 仅兼容读取） |
| `authority_level` | `national_standard`/`industry_standard`/`local_standard`/`official_technical`/`peer_reviewed`/`standard_draft`/`historical`/`synthetic`/`unknown` 等 |
| `verification_status` | `verified` / `pending` / `rejected` |
| `effective_date` | 生效日期（字符串，可空） |
| `fetched_at` | 采集时间（ISO-8601，可空） |

`status="staging"` 的文档**不会**出现在问答引用中；前端可据此显示"待发布"。

### 13.9 引用对象新增字段

`CitationOut` 与 SSE `sources[]` 增加：

| 字段 | 说明 |
|---|---|
| `source_type` | `document` 或 `faq` |
| `faq_id` | FAQ 引用时非空；此时 `document_id`/`version_id`/`chunk_id` 为 `null` |
| `evidence_level` | `L1_original` / `L2_verified_faq`（L3/L4 永不出现） |
| `authority` | 来源权威等级（见 `app/authority.py`） |
| `verification_status` | `verified` |
| `publisher` | 发布机构 |
| `source_url` | 原文 URL |
| `supplemental` | `true` 表示该条是第二阶段补充的 FAQ 证据 |

聊天请求体已新增 `answer_mode`，语义与错误码见 2.4.1；其中 `document_faq_rag`/`faq_direct` 需服务端开关开启，默认仅 `document_rag` 可用。

## 14. 数据管理查询 API（2026-10-21 新增）

这一组接口是**只读查询**，前缀 `/api/manage`，与既有 `/api/documents` 分开：
旧列表继续返回 `DocumentOut[]`，不会因为分页改造而破坏旧客户端。

### 14.1 `GET /api/manage/documents`

服务端分页、稳定排序、可组合筛选。参数：

| 参数 | 说明 |
|---|---|
| `q` | 标题/分类/机构/URL/source_id 模糊搜索 |
| `status` | 逗号分隔：`active,staging,failed,deleted`；`failed` 是派生状态（无当前版本且最近一次解析失败），不会同时出现在 `staging`；不传默认排除 `deleted` |
| `published` | `true`：`status=active` + `verification_status=verified` + 有当前版本；`false` 取反 |
| `technical_review` / `domain_review` | 逗号分隔的审查状态；两条轴独立 |
| `document_type` | `standard` / `standard_draft` / `technical_guidance` / `research` / `synthetic` / `other` |
| `source_type` | `pdf` / `html`；历史 `web` 在输出中归一为 `html` |
| `authority_level` / `language` / `species` / `category` / `license` / `source_id` | 精确筛选 |
| `sort` | `created_desc`（默认）、`created_asc`、`updated_desc`、`title_asc`、`title_desc`、`year_desc` |
| `limit` / `offset` | `limit` 1–100，默认 25 |

响应：

```json
{
  "items": [{"id": "...", "title": "...", "status": "staging", "published": false,
             "retrievable": false, "document_type": "standard_draft",
             "parent_chunks": 3, "child_chunks": 12, "...": "..."}],
  "total": 100, "page": 1, "page_size": 25, "pages": 4,
  "has_next": true, "has_prev": false, "sort": "created_desc", "applied_filters": {}
}
```

要点：

- `total` 是**筛选后的全库计数**，不是当前页长度。
- `published` 只表示发布状态；`retrievable` 还要求当前版本 `ready`。前端不要用 `current_version_id` 代替发布状态。
- `staging` 即使已有当前版本、块已入索引，也不是 published。
- 同一来源的多版本/重复上传通过规范化 URL / `content_hash` 去重后计入 `/stats` 的有效规模。

### 14.2 `GET /api/manage/stats`

返回全库聚合：文档状态（`by_status` 只统计未删除，`by_status_including_deleted` 另给删除桶）、核验、材料性质、两条审查轴、独立来源（有效/待审/重复归并）、版本（`versions.total` 含删除文档，`live_total`/`deleted_total` 分开）、父/子块（全部/当前 active/当前 staging/删除版本）、FAQ 审核与**实际 Qdrant FAQ 点数**、来源登记与最近批次。删除记录计入 `records_including_deleted`，不计入可信度分布或有效规模。`published` 只要求 active+verified+当前版本；`retrievable` 还要求当前版本 `ready`，二者必须分开显示。

### 14.3 `GET /api/manage/facets`

返回筛选面板的计数：`status`、`category`、`species`、`source_type`、`authority_level`、`technical_review_status`、`domain_review_status`、`language`、`license`、`document_type`。`include_deleted=true` 只影响 `status` 桶；其余分面始终只统计未删除资料。

### 14.4 `GET /api/manage/documents/{document_id}`

文档详情：来源/存储/许可证、当前版本与历史版本、任务、解析块预览、风险标记（`review_flag_details`），以及 `source`/`storage`/`review` 三个说明性对象。**不改变任何状态。**

### 14.5 `GET /api/manage/documents/{document_id}/chunks`

参数 `version_id`、`role=parent|child`、`page`、`q`、`limit`、`offset`。`version_id` 不传时取当前版本；不属于该文档的版本返回 404。

### 14.6 `GET /api/manage/jobs`

参数 `status`、`kind`、`document_id`、`limit`、`offset`；返回任务状态、进度、`attempts`、失败原因、版本号与文档标题。

### 14.7 FAQ 管理查询

- `GET /api/manage/faq?q=&review_status=&evidence_status=&usage_scope=&species=&indexed=&limit=&offset=`
- `GET /api/manage/faq/{faq_id}`：答案、审核来源、`supporting[]`（每条支撑原文的文档/版本/页码/引文/可用性）。
- `GET /api/manage/faq/stats/summary`：数据库审核计数、`verified_indexed`（`indexed_at` 非空）、Qdrant `index_points`；二者可能不同。

`program_seeded`（数据集 `seed:*` 或标记 `seeded_from_active_document`）表示**程序从已发布原文复制**，`review_provenance_label` 必须显示为非专家审核；`domain_review_status` 为 `not_recorded` 时不得显示成专家确认。

### 14.8 `GET /api/manage/capabilities`

服务端能力开关：`answer_modes[]`（含 `available`/`reason`）、`faq_retrieval`、`faq_direct_answer`、`max_sources`、`faq_supplement_k`。前端只能展示 `available=true` 的模式，不得通过按钮或请求体绕过全局关闭。

### 14.9 引用对象的分支与可用性

`source_type` 是证据分支（`document` / `faq`）；`media_type` 是物理形态（`pdf` / `html` / `faq`）。二者不可混用：

- PDF：`document_id`/`version_id`/`page`/`page_end`/`locations[]` 可用；`location`/`bbox` 只是第一处定位，跨页父块必须读取 `locations[]` 才能完整展示全部页码与 bbox。
- HTML：有 `document_id`/`version_id`，**没有** PDF 页码/bbox；`locations[]` 是块/段落锚点，不能渲染为 PDF 高亮。
- FAQ：`faq_id` 非空，`document_id`/`version_id`/`page` 为 `null`；FAQ 本身不是 PDF，支撑原文在 `/api/manage/faq/{id}` 的 `supporting[]`。

历史消息读取（`GET /api/sessions/{id}/messages`）的 `CitationOut` 新增：

| 字段 | 说明 |
|---|---|
| `media_type` | `pdf` / `html` / `faq` |
| `source_url` | 原文链接（FAQ 为原始来源） |
| `document_status` | 当前文档状态；FAQ 为 null |
| `available` | 该历史引用现在是否仍可打开 |
| `unavailable_reason` | `document_deleted` / `document_missing` / `version_missing` / `faq_missing` / `faq_not_verified` / `faq_support_invalid` |
| `locations` / `page_end` | PDF 全部页码与 bbox；HTML 为块锚点；FAQ 为空 |

`GET /api/documents/{document_id}/citations` 新增可选 `version_id`，并返回每条引用的 `locations[]`/`page_end`。阅读器**必须**传当前打开的版本，否则后端不会把旧版本的 bbox 套到新版本上；跨页引用要逐一定位 `locations[]`，不能只画第一处。

## 12. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-20 | 初版；按真实 FastAPI/OpenAPI 整理；新增 `GET /api/debug/stats`、文档 source 元数据字段、`chunk_id`/`location`/`bbox` 顶层字段；文档列表支持 `q/status/limit/offset` |
| 2026-10-20b | 复核真实响应：补充 `/api/health` 的 `max_sources`/`rerank_top_k`；修正 PDF 原文件接口已支持 Range/206（不是“无特殊处理”）；补充 18 路由回归测试说明 |
| 2026-10-20c | Planner 结构化任务：新增 `planner_tasks`，记录子问题 facet/继承字段/effective_query；明确非 species hard 约束降级规则；补充 simple 跳过与 `applicable_constraints` |
| 2026-10-21 | 新增第 13 节：文档 `promote`、FAQ 列表/详情/统计/复核、数据来源与导入审计；`CitationOut` 增加 `source_type`/`faq_id`/`evidence_level`/`authority`/`verification_status`/`publisher`/`source_url`/`supplemental`；FAQ 检索默认关闭 |
| 2026-10-21b | 新增第 14 节 `/api/manage/*` 服务端分页/筛选/统计/详情与 FAQ 管理；引用增加 `media_type`/`locations[]`/`page_end`/可用性与版本过滤；旧 `/api/documents` 数组契约保持不变 |
