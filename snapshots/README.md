# 语料快照

一次快照 = 某一时刻 active 语料的不可变副本 + 一份可复算的指纹。

| 快照 | 冻结时间 (UTC) | 文档 | corpus_digest |
|---|---|---|---|
| `kb-v1_20261022` | 2026-10-22T02:15:23Z | 1548 | `2f6f744358074a8368059c644f621605d7058bb8b947c5b062b4662610d4316e` |

## 目录内容

| 文件 | 是否入库 | 内容 |
|---|---|---|
| `snapshot.json` | 是 | 清单：计数、口径分布、许可审核记录、门禁快照、索引状态、注意事项、全部产物的 sha256 |
| `documents.jsonl.gz` | 是 | 每篇文档一条记录：来源/许可/审核/版本/hash/块统计/索引点数/门禁判定/单篇 digest |
| `chunks.jsonl.gz` | 否（本地） | 335 088 个块（父子）的全文与 hash，供逐块复现与引用核对；73 MB，不入 git |
| `SHA256SUMS` | 是 | 上面两个数据文件的 sha256 |

目录权限为只读；`freeze_snapshot.py` 不会覆盖已存在的快照。

## 为什么 corpus_digest 可复现

`documents.jsonl` 每条记录有一个 `document_digest`，覆盖该文档的冻结事实（标题、来源、许可、
技术审核、版本、源文件 sha256、块摘要）。`corpus_digest` 是排序后的
`document_id:document_digest` 列表的 sha256。数据库不变时重新冻结得到同一个值；
`gate` 判定属于派生结论，刻意不进入 digest，规则调整不会改写语料指纹。

## 校验

```bash
cd apps/api
.venv/bin/python ../../scripts/verify_snapshot.py \
  --snapshot ../../snapshots/kb-v1_20261022 --check-db --strict
```

`--check-db` 会对比当前 active 集合：新增 / 删除 / 当前版本或 content_hash 变更。
2026-10-22 冻结时实测 `+0 -0 ~0`。

## 快照口径（kb-v1）

- active 1548：WorldFish 723、国家级推广 459、地方 222、标准 98、期刊 43、其他 3。
  - 其中 3 篇原 `source_trust=NULL` 的地方标准在 2026-10-22 补齐为 `official_standard`
    （2 篇来自 dbba 平台、1 篇来自海南省市场监管局），所以标准从 95 变为 98、其他从 6 变为 3。
- 四层状态互不替代：
  - `source_trust`：international_org 723 / official_national 459 / official_local 222 /
    official_standard 98 / research_institute 43 / 未判定 3
  - `licence_class` + `index_eligibility`：cc_explicit 567 / gov_document_cn 459 /
    unclear 320 / repository_open_access 199 / 未判定 3；
    eligible 1347 / pending_licence 200 / ineligible 1
  - `technical_review_status`：pass 722 / warn 544 / pending 281 / fail 1
  - `domain_review_status`：**1548 篇全部 pending**。本快照不声称发生过任何专家审核。
- 门禁：1347 篇满足现行发布规则，201 篇不满足（200 篇 `pending_licence`、5 篇
  `licence_review=rejected`、3 篇无审核记录、1 篇技术审核 fail；原因可重叠）。
- 许可证据类型（`licence_reviews.evidence_kind`）：
  - `item_licence_field` 526 篇：WorldFish 单篇 `dc:rights`（CC BY 352、CC BY-NC 139、
    CC BY-NC-ND 31、公有领域 2、GPL 1、NC-only 1）
  - `policy_inference` 681 篇：nftec 病害预报 435（著作权法 §5 推断）、地方技术文章 222、
    nftec 新闻 24（§24(6) 科研豁免）
  - `platform_public_access` 98 篇：地方标准公开平台
  - `publisher_policy` 43 篇：期刊 CC BY-NC-ND 声明
  - `repository_terms` 192 篇：无单篇权利字段，**unverified**，已隔离

## 隔离与恢复

200 篇无批准依据的文档已从正式索引移除：`index_eligibility='pending_licence'`（1 篇
技术失败为 `ineligible`），Qdrant 向量删除，但行、源 URL、原始文件、许可记录全部保留，
`metadata.licence_isolation` 记录时间/原因/审核 scope。删除清单见
`data/reports/licence_isolation_20261022T021007Z.json`，恢复命令：

```bash
.venv/bin/python scripts/isolate_licence_pending.py --restore --apply --confirm \
  --manifest ../../data/reports/licence_isolation_20261022T021007Z.json
```

恢复只对 `licence_reviews.decision='approved'` 的文档生效。

## 已知缺口（冻结时）

- 10 篇 `eligible` 文档没有 current_version / 子块，可发布但不可检索（总量 1347 可发布，
  1337 实际可检索）。
- 11 篇 active 文档没有源文件或版本，`file.sha256` 为 null。
- 1 组 2 篇 `content_hash` 重复（重印），快照按原状保留，未合并计数。
- Qdrant 中另有 14 761 个点属于已删除/历史版本（stale），检索已按 eligible 过滤，
  不参与召回；清理属于独立维护动作。
- 快照 `git.dirty=true` 是因为冻结时工作区存在其他工具（Qoder）的未提交改动；
  本快照自身的脚本与迁移已提交在 `8d11601`。