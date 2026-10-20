# Aquaculture RAG 后端 API Contract

> 版本：2026-10-20
> 依据：`apps/api` 当前真实代码与 `GET /openapi.json`，不是设计稿。
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
  "retrieval_mode": "hybrid_rerank"
}
```

| 字段 | 必填 | 类型/枚举 | 说明 |
|---|---|---|---|
| question | 是 | string 1–2000 | 问题；前后空白会被去除 |
| session_id | 否 | UUID/null | 不传则新建会话 |
| category | 否 | string/null | 文档分类硬过滤，例如 `水质管理` |
| species | 否 | string/null | 品种硬过滤；建议只传单一品种 |
| retrieval_mode | 否 | `dense`/`bm25`/`hybrid`/`hybrid_rerank` | 默认 `hybrid` |

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
- `llm_planner` 在规则模式为 `null`；开启后包含 `used_llm`、`error`、`attempts`、`plan`、`subquestions`。
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
- `claim_summary.support_rate` 是词面支持率，**不是 NLI/事实准确率**；论文中必须标注 `lexical_overlap_v0`。
- `claims` 仅在 `ENABLE_CLAIM_VERIFICATION=true` 时出现（默认 true）。

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
      "path_entity_ids": ["...", "..."]
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
- `max_hops` 默认 2，`graph_max_related` 默认 12，防止扩展爆炸。
- 图谱扩展只帮助召回候选 chunk，**不等于证据充分**；仍必须经过 `gate` 和引用校验。

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
- 当前是词面重叠，不是语义蕴含；不要展示为“事实已核实”。

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
- 当前无 Range 请求特殊处理；PDF.js 按整文件加载即可。
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
  "reranker_model": "BAAI/bge-reranker-v2-m3"
}
```

- `status=ok` 仅当三个组件都 ok；否则 `degraded`。
- `llm_configured` 只检查配置字段是否存在，**不发起付费调用**；真正可用性要看一次聊天或 `/scripts/check_llm.py`。
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
| planner_subquestions | 规划出的子问题 |
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
  "hard_filter": "中华绒螯蟹",
  "subquestions": ["..."]
}
```

安全边界（前端文案必须一致）：

- LLM 推断的品种/约束默认是 **soft**，不会成为未经验证的硬过滤。
- `accepted_as_hard` 只表示通过校验；`filter_applied=true` 才表示该约束真的进入了 Qdrant 过滤。
- `scope` 取 `document_filter` / `retrieval_requirement` / `soft_context`；目前真正用于 Qdrant 硬过滤的仍只有文档级 `species_filter` 和请求显式 `category`。
- `planner_source=llm` 不等于“IR 一定正确”；失败会安全回退 `rules`，并在 `error` 中记录。
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

## 12. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-20 | 初版；按真实 FastAPI/OpenAPI 整理；新增 `GET /api/debug/stats`、文档 source 元数据字段、`chunk_id`/`location`/`bbox` 顶层字段；文档列表支持 `q/status/limit/offset` |
