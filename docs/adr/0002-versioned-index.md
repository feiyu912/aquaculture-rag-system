# ADR-0002：文档版本化索引与延迟清理

| 项 | 内容 |
|---|---|
| 状态 | 已接受 |
| 日期 | 2026-10-19 |
| 决策者 | 项目组 |
| 相关文档 | [技术方案](../technical-plan.md) 第 3.3、4 节 D2、第 6 节 |

## 背景

旧方案写“切换文档生效状态，并调用 Qdrant 原子级清除旧向量”。PostgreSQL 与 Qdrant 之间不存在跨数据库 ACID 事务，该表述在工程上不成立，也无法保证更新失败时的一致性。

## 决策

采用**版本化索引 + 先激活后延迟清理**：

1. `doc_id` 稳定，更新产生新的 `doc_version_id`。
2. 新版本完成解析、切分、向量化、写入并校验后，才允许激活。
3. PostgreSQL 的 `kb_documents.current_version_id` 是唯一生效标志。
4. 检索时用查询开始时的生效版本快照过滤 Qdrant。
5. 旧版本先置 `archived`，延迟 7 天清理 point 与 chunk。
6. 第一版整文档重建，不做块级差异更新；SHA-256 只用于判断文件内容是否相同。

激活事务只发生在 PostgreSQL：

```text
BEGIN;
  SELECT ... FOR UPDATE;
  UPDATE kb_documents SET current_version_id = :new;
  UPDATE kb_document_versions SET status='archived'
    WHERE document_id=:doc AND id<>:new AND status='ready';
COMMIT;
```

## 备选方案

| 方案 | 不采用的原因 |
|---|---|
| 先删旧向量再切版本 | 删除失败会留下“新版本未生效、旧版本已毁”的不可恢复状态 |
| 先切版本再同步删旧向量 | 删除失败会留下旧向量，但可通过过滤兜底；仍不如延迟清理稳 |
| 跨库两阶段提交 | Qdrant 不参与分布式事务；引入自研补偿复杂度高、收益低 |
| 块级差异更新 | 需要可靠的块对齐与变更检测，超出本科项目范围 |
| 每版本一个 collection + alias 切换 | 可行但集合数量膨胀、运维复杂；payload 过滤已足够 |

## 后果

- Qdrant 可能短期保留旧版本 point，但检索过滤保证不可见。
- 清理失败只产生存储垃圾，不影响回答正确性。
- 历史引用依赖 `chat_citations` 快照，不依赖旧向量是否还在。
- 保留期内可快速回滚；超过保留期需从原始 PDF 重新索引。
- 需要一个对账任务比较 PostgreSQL chunk 数与 Qdrant point 数，发现孤儿数据。