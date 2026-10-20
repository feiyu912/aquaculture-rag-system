# 前端 → 后端：API Contract 需求清单

> 面向 DSH（后端）。以下均为**前端无法自行实现**、且会直接影响用户可见行为的问题。
> 每条都给出了当前事实、期望的最小改动、兼容性影响和验收方式。
> 原则：**不重写后端业务逻辑**，只请求补充缺失的数据或接口。

## R1（重要）跨页引用只返回第一个 location

### 当前事实

`apps/api/app/retrieval/service.py` 的 `Evidence.as_source()` 只带一个坐标：

```python
location = parent.locations[0]   # 只取第一个
```

而 `kb_chunks.locations` 本身是**列表**。当前库内 592 个 chunk 中有 **65 个是跨页块**
（`len(locations) > 1`），例如：

```text
parent 8e8c4185  page_from 1
  locations[0] = {page: 1, bbox: [79.90, 65.60, 560.73, 526.38], ...}
  locations[1] = {page: 2, bbox: [454.83, 768.02, 547.05, 782.29], ...}
```

### 后果（已在浏览器中实测）

一条引用如果正文的 chunk 跨了第 1–2 页，PDF 阅读器只会在**第 1 页**高亮，
第 2 页的那半段无法定位。用户点「在 PDF 原文中定位」看到的高亮范围与引用文本不完全对应。

### 期望的最小改动

在 `Evidence.as_source()` 中增加一个**新增字段**（不要改动现有 `location`）：

```python
"locations": list(self.locations),   # 全部 location，顺序与阅读顺序一致
```

`location` 保持为 `locations[0]`，因此**旧客户端与旧数据完全兼容**。

### 验收

```bash
curl -s "http://127.0.0.1:8000/api/documents/<db36-doc-id>/citations" | python3 -m json.tool | grep -A6 locations
```

前端拿到 `locations` 后，第 3 节的阅读器即可对每一页分别渲染高亮。

---

## R2 检索调试页无法浏览历史 Trace

### 当前事实

```http
GET /api/debug/query-logs/{request_id}
```

只支持**按 request_id 精确查询**。前端调试页只能：
- 从智能问答页点「检索详情」带 `request_id` 跳转；
- 或手工粘贴一个已知的 request_id。

这让调试页无法回答「最近一小时有哪些请求、哪些被拒答、哪些走了重排」。

### 期望的最小改动

新增一个**只读列表**接口（与现有 trace 接口同前缀）：

```http
GET /api/debug/query-logs?limit=50&hours=24&route=rag&insufficient=true
```

返回建议：

```json
[
  {
    "request_id": "c4beddc1457d4d2d8b7c17cdb0c564e7",
    "question": "中华绒螯蟹扣蟹池塘培育对溶解氧有什么要求？",
    "route": "rag",
    "retrieval_mode": "hybrid_rerank",
    "reranker": "BAAI/bge-reranker-v2-m3",
    "sufficient": true,
    "evidence_count": 5,
    "model": "deepseek-v4.1-flash-1017",
    "total_ms": 17900.0,
    "created_at": "2026-10-20T09:41:22.101Z"
  }
]
```

前端据此在调试页左侧加一个「最近请求」列表，点击即载入完整 Trace。

> `/api/debug/stats` 已经提供了聚合口径，这里补的是**逐条**列表，两者互补。

### 验收

```bash
curl -s "http://127.0.0.1:8000/api/debug/query-logs?limit=5" | python3 -m json.tool
```

---

## R3 被中断的回答在库里留下 `status="streaming"` 的悬挂消息

### 当前事实

`POST /api/chat/stream` 在**开始流式之前**就写入了 assistant 消息行
（`status="streaming"`, `content=""`）。如果此时进程被重启 / 被 kill，
这行数据会永久停留在 `streaming` + 空内容状态：

```json
{"role": "assistant", "status": "streaming", "content": "", "meta": {"request_id": "..."}}
```

实测中已出现多条（开发期间后端频繁重启）。

### 前端现状（已处理）

前端现在把 `status === "streaming"` 的历史消息渲染为
「回答未完成 / 生成过程中连接被中断，没有留下任何内容。」并提供「重试」，
不再出现空白气泡。

### 期望的后端处理（可选，清理性质）

worker 或 API 启动时把**超过一定时间仍处于 `streaming`** 的消息标记为
`failed`（或新增 `interrupted` 状态），并在 `meta` 里写明原因，例如：

```json
{"status": "failed", "meta": {"error": "server_restart_during_stream"}}
```

这样 `GET /api/sessions/{id}/messages` 返回的数据本身就是自洽的，
前端也就不再需要把 `streaming` 解释为「中断」。

---

## R4 引用条数上限需要能被前端感知（已完成，仅记录）

### 当前事实

`MAX_SOURCES`（默认 5）决定了一次回答最多产生多少条引用；
`RERANK_TOP_K`（默认 8）决定重排后保留多少候选。

### 已完成的改动

`GET /api/health` 现在额外返回：

```json
{"max_sources": 5, "rerank_top_k": 8}
```

前端据此在引用面板显示 `5 / 5`，并在触顶时提示「已达引用上限」，
避免用户以为引用被随机截断。

### 说明（不需要改动）

上限本身是**产品与论文口径的共同选择**，不应由前端调整：
提高上限会同时增加模型上下文与回答时延，并可能引入更无关的引用。
需要调整时改服务端 `.env` 即可，前端会自动跟随。

---

## 优先级

| 编号 | 主题 | 优先级 | 前端影响 |
|---|---|---|---|
| R1 | 跨页 location 列表 | **高** | 跨页引用无法完整高亮 |
| R2 | Trace 列表接口 | 中 | 调试页无法浏览历史请求 |
| R3 | 中断消息的状态收敛 | 低 | 前端已能兜底显示 |
| R4 | 引用上限透出 | 已完成 | — |
