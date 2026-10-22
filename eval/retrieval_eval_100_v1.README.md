# 检索评测集 v1（100 题中文）

| 项目 | 值 |
|---|---|
| 文件 | `retrieval_eval_100_v1.jsonl` |
| 题量 | 100 |
| 来源分层 | 标准 29 / 国家级病害预报 20 / 地方技术文章 36 / 期刊论文 15 |
| 语料快照 | `snapshots/kb-v1_20261022`（corpus_digest `2f6f7443…4316e`） |
| 标注状态 | `template_generated_pending_human_review` |
| 与既有题目最大相似度 | 0.143（5-gram Jaccard，阈值 0.55） |
| 校验 | 100/100 gold chunk 存在、属于 eligible 文档、且有点在 Qdrant |

生成脚本：`scripts/build_retrieval_eval_100.py`；校验脚本：`scripts/validate_retrieval_eval.py`。
人工复核表：`eval/review/retrieval_eval_100_v1_review.csv`（逐题核对后可填 verdict/notes）。

## 字段

```json
{
  "id": "E001",
  "question": "……",
  "reference_answer": "……（取自 gold 块原文）",
  "question_type": "standard_section | standard_scope | forecast | local_tech | journal_conclusion",
  "group": "standard | national | local | journal",
  "species_label": "……或 null（仅作分层标签，不参与检索过滤）",
  "gold": [{"document_id": "...", "version_id": "...", "chunk_id": "...",
            "parent_chunk_id": "...", "grade": 2,
            "title": "...", "page": 5, "evidence": "..."}],
  "split": "test",
  "annotation_status": "template_generated_pending_human_review",
  "annotation_basis": "……"
}
```

`gold` 只有一个块，是**充分**证据：参考答案的全部数值/结论都能在该块中找到。

## 题目怎么来的

- 标准：按章节标题（`heading_path`）提问，如“《DB43/T 2984-2024》对‘4 配套设施’提出了哪些要求？”
- 国家级预报：按“年-月-省”提问，如“2025年4月山东省水产养殖需要重点防控哪些病害？”
- 地方文章：按“物种 + 主题 + 章节”提问，不引用标题。
- 期刊：按论文主题提问，gold 取结果/结论块。

排除集：`data/hf_qa/eval/*.jsonl`（QA 数据组的 CN/EN 题）与 `eval/real_questions_v1.jsonl`，
共 3 233 条；按 5-gram Jaccard > 0.55 拒绝，实测最高 0.143，无重复。

## 已知局限（必须在论文中如实说明）

1. **未做人工终审**：题目由模板生成，参考答案为块原文抽取。`annotation_status` 保持
   `pending_human_review`；`domain_review_status` 仍全部为 `pending`。
2. **标准题引用标准号**：标准号出现在题面，BM25 可凭编号直接命中，会高估词法检索的
   标准类表现。29 题中 20 题属于此类；对比实验时应按 `question_type` 分层报告。
3. **地方题存在套话**：部分题面为“{物种}{主题}中，{章节}有哪些要求？”，措辞机械，
   但不泄漏文档标题，gold 与答案对齐已逐题校验。
4. **语言覆盖**：100 题全部为中文，语料中 526 篇可发布的 WorldFish 英文文献未覆盖
   （跨语言检索需单独建集），因此本集指标不能代表全库。
5. **来源噪声**：地方来源含少量非水产文章（如荔枝、菠萝、贝瓷），生成时已按水产词表
   过滤，但过滤是词表级的，不等于人工确认每篇主题相关。

## 使用

```bash
cd apps/api
.venv/bin/python ../../scripts/validate_retrieval_eval.py
uv run python ../../scripts/evaluate_retrieval_metrics.py \
  --dataset ../../eval/retrieval_eval_100_v1.jsonl --out ../../eval/runs/v1
```

复核通过前，运行结果只能作为**流程演练**，不能写进论文的最终实验表格。