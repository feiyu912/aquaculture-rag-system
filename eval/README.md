# 评测数据与脚本

## 目录

- `sample_questions.jsonl`：**演示用合成测试集**，不是论文 Ground Truth。字段说明见下。
- `../scripts/evaluate.py`：调用运行中的 API，批量跑多种检索方案，导出 JSONL 与 CSV。

## JSONL 字段

```json
{
  "id": "q1",
  "question": "中华绒螯蟹养殖对溶解氧有什么要求？",
  "reference_answer": "溶解氧宜保持在 5 mg/L 以上，低氧时及时增氧。",
  "gold_pages": [1],
  "gold_title": "水产养殖水质管理示例资料",
  "species": "中华绒螯蟹",
  "category": "水质管理",
  "expect_insufficient": false,
  "notes": "合成资料，仅用于流程验证"
}
```

- `reference_answer` 必须由人依据原文标注，不能把 LLM 生成的答案直接当 Ground Truth。
- `gold_pages` 用于 page-level retrieval hit / MRR；正式实验应补充 `gold_chunk_ids` 或人工证据句。
- `expect_insufficient=true` 表示该问题应触发证据不足分支，不参与检索命中率统计。

## 运行

```bash
cd apps/api
uv run python ../../scripts/evaluate.py \
  --dataset ../../eval/sample_questions.jsonl \
  --modes dense,bm25,hybrid,hybrid_rerank \
  --out ../../eval/runs/demo
```

输出：

- `results.jsonl`：每条 case × mode 的 sources、answer、citation check、timings、配置快照。
- `summary.csv`：按 mode 聚合的 Hit@k、MRR、引用有效率、覆盖率、延迟、拒答率。
- `run_config.json`：数据集路径、模式、时间、模型、collection。

## 指标边界

- **Hit@k / MRR** 是 page-level 代理指标；页码命中不等于证据句完全支持答案。
- **引用有效率** 只检查编号是否存在；**支持性**需要 `POST /api/citations/{id}/verify` 或后续 NLI/人工标注。
- **证据不足** 用规则门槛判定，必须报告阈值，不能当作语义蕴含模型。
