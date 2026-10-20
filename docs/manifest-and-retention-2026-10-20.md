# 索引 Manifest、软删除保留与 MPS 多进程（2026-10-20）

> 三项都是“可复现/可运维”问题，不改检索链路与 gate 阈值。
> 本轮真实命令与输出见每节末尾。

## 1. Manifest 纳入 BM25 tokenizer hash

**问题**：manifest 只记录 dense embedding 模型、向量维度和 chunk 配置。BM25 稀疏向量
由客户端 tokenizer 生成（jieba 版本 + `CUSTOM_TERMS` + 停用词 + CRC32 index），换
tokenizer 后同一段正文会编码成不同的 sparse vector，但 manifest 仍然 `ok`。

**实现**（`app/retrieval/bm25.py`）：

```python
def tokenizer_config() -> dict:
    return {
        "implementation": "jieba+custom_terms",
        "jieba_version": getattr(jieba, "__version__", "unknown"),
        "custom_terms": sorted(CUSTOM_TERMS),
        "stopwords": sorted(STOPWORDS),
        "cjk_pattern": CJK_RE.pattern,
        "alnum_pattern": ALNUM_RE.pattern,
        "index_fn": "crc32&0x7fffffff",
    }

def bm25_config_hash() -> str:  # sha256(canonical json)
```

- `index_manifests.bm25_config_hash`（migration `0014`），空字符串兼容旧 manifest；
- `check_manifest(..., bm25_config_hash=...)` 不匹配时返回
  `manifest_bm25_config_mismatch`（只告警，不静默通过）；
- `upsert_manifest` 写入；ingestion、reindex、cleanup 刷新时都会带上；
- 检索响应的 `config.index_compatibility.manifest.warnings` 因此能看到该告警。

真实回填与验证（cwd `apps/api`）：

```text
BEFORE {"ok": false, "warnings": ["manifest_bm25_config_mismatch"], "bm25_config_hash": ""}
AFTER  {"ok": true,  "warnings": [], "bm25_config_hash": "e3851c722cd28f3a34f4ef8f1faf595d844274c6d3831b2c72f23603c81cf13f"}
jieba 0.42.1
```

回填只写 manifest 的 hash 字段，不重算向量；本次 190 个点的 sparse 向量已在
`rebuild_sparse_vectors.py --apply` 后审计过（190 扫描 / 2 变更 / 0 缺失），与当前
tokenizer 一致。

## 2. 软删除保留策略

**问题**：`purge_deleted_vectors` 原来会立刻删除所有 `status=deleted` 文档的 Qdrant
点。误删无法在不重新 ingest 的情况下恢复，且和“DB 行与 PDF 保留”的承诺不一致。

**实现**：

- `kb_documents.deleted_at`（migration `0015`）；删除接口写入 `datetime.now(UTC)`；
- `soft_delete_retention_days` 默认 **7 天**；`retention_cutoff()` / `is_expired()`
  是纯函数，旧数据没有 `deleted_at` 时回退 `updated_at`，naive 时间按 UTC 处理；
- `purge_deleted_vectors` 只处理 `deleted_at < now - retention` 的版本，其余原样保留；
- 结果明确区分 `versions_with_points` / `retained_versions` / `retention_cutoff`；
- `--retention-days 0` 是显式立即清理（运维/测试），默认 dry-run；
- worker 的 `cleanup_deleted_vectors` 与 CLI 共用同一实现，不会两套逻辑漂移。

真实 dry-run（默认 7 天，未加 `--apply`）：

```json
{
  "dry_run": true,
  "collection": "kb_chunks_bge_m3_v1",
  "retention_days": 7,
  "retention_cutoff": "2026-10-13T07:31:32.701491+00:00",
  "deleted_documents": 0,
  "versions_with_points": 0,
  "points_to_remove": 0,
  "retained_documents": 89,
  "retained_versions": 111
}
```

解释：这 89 个文档是今天软删除的（旧的重复版本/测试数据），其 derived points 已被
之前的清理删除，所以 `points_to_remove=0`；7 天内仍保留 DB 行、PDF 和恢复能力。
检索按 `current_version_id` 过滤，不会召回它们。

## 3. MPS 多进程策略

**问题**：embedder/reranker 已有进程内锁 + 跨进程 advisory file lock，但 ARQ worker
默认 `max_jobs=10`：同一 worker 里多个 job 并发时，每个 job 会各自加载一份模型到
同一块 Metal 设备，文件锁只能让它们排队，不能避免显存/驱动崩溃。

**实现**（`app/worker.py`）：

```python
def serial_inference_required() -> bool:
    return "mps" in {resolve_device(settings.embedding_device),
                     resolve_device(settings.reranker_device)}

def effective_max_jobs() -> int:
    return 1 if serial_inference_required() else max(1, settings.worker_max_jobs)

class WorkerSettings:
    max_jobs = effective_max_jobs()
```

- `worker_max_jobs=4` 是可配置上限；MPS 时强制 1；
- 跨进程锁仍保留（uvicorn 与 worker 同时存在时串行化 Metal 调用）；
- 真实输出：`device mps serial True max_jobs 1 configured 4`。

> 未做：把模型推理拆到独立推理进程（需要新的 IPC 协议与队列），本轮只是把“多进程
> 并发提交 Metal”变成明确禁止，并让配置可见。

## 4. 测试与命令

```bash
cd apps/api
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests --output-format concise
.venv/bin/python ../../scripts/purge_deleted_vectors.py            # dry-run
.venv/bin/python ../../scripts/migrate_db.py                       # additive migrations
```

新增测试：

- `tests/test_index_manifest_config.py`：hash 稳定性/变更敏感性、mismatch 告警、
  匹配时不告警、未提供期望 hash 时不误报；
- `tests/test_soft_delete_retention.py`：保留窗口边界、`deleted_at` 回退
  `updated_at`、naive 时间、缺失时间戳、MPS 强制单 job / CPU 可配置。 

## 5. 已知边界

- manifest 的 BM25 hash 只能证明“当前代码的 tokenizer 与 manifest 一致”，不能证明
  历史点是用它生成的；要更强保证需要逐点存 `tokenizer_hash`，成本高，本轮未做。
- 保留期内恢复文档需要把 `status` 改回 `active` 并恢复 `current_version_id`；当前
  没有“撤销删除”接口，只有数据保留。
- MPS 单 job 策略只覆盖 ARQ worker；`uvicorn --workers N>1` 仍会让 N 个进程各持一份
  模型，部署时应使用 1 个 web 进程（README 的 MPS 说明已注明）。