# HF 问答数据集对接调研（老师建议数据源的格式适配）

> 调研日期：2026-10-21。背景：老师建议数据参考农业农村部及各地农业农村部门发布的养殖技术资料（**网页和 PDF**），
> 并使用 Hugging Face 问答数据集（筛选"对虾、河蟹、草鱼、罗非鱼、鱼苗、虾苗、溶氧、氨氮、亚硝酸盐、池塘"等关键词）。
> 本文回答一个问题：**HF 问答对的格式和当前系统的格式差在哪、怎么接进去。**

## 一、数据集调查结果

| 数据集 | 规模 | 格式 | 语言 | 协议 | 判定 |
|---|---|---|---|---|---|
| [Mxode/Chinese-QA-Agriculture_Forestry_Animal_Husbandry_Fishery](https://huggingface.co/datasets/Mxode/Chinese-QA-Agriculture_Forestry_Animal_Husbandry_Fishery) | 927,864 条 | `{"id","prompt","response"}` parquet | 中文 | CC-BY-SA-4.0 | **主用**。水产子集 22,240 条，清洗后 **21,088 条**（品种层 1,303 / 通用层 19,785） |
| [KurmaAI/AQUA-Test-Dataset](https://huggingface.co/datasets/KurmaAI/AQUA-Test-Dataset) | 20,000 条 | `{"question","response"}` jsonl | **英文 19,721 / 中文仅 279** | MIT | **低直接可用性**。水产主题但答案是 LLM 生成的英文长文；仅作问题类型参考 |

- 网络说明：huggingface.co 直连超时，**HF 一律走 [hf-mirror.com](https://hf-mirror.com) 镜像**（实测可用）。
- HF 站内其余 aquaculture 数据集扫描结论：以产量统计、图像检测类为主，**无更优中文水产问答语料**。
- 落盘位置（登记于 `data/meta/sources.jsonl`）：
  - `data/raw/hf/Chinese-QA-AFAF-train-v2.parquet`（全集 172MB）
  - `data/raw/hf/aquaculture_subset.parquet`（水产子集 22,240 条）
  - `data/raw/hf/AQUA-test.jsonl`（20,000 条）
  - `data/meta/qa_candidates.jsonl`（**清洗后候选池 21,088 条**，字段已按系统 seed 格式预留）
- 关键词命中（问题侧）：池塘 1,852 / 亚硝酸盐 731 / 对虾 724 / 草鱼 661 / 鱼苗 614 / 氨氮 584 / 河蟹 593 / 虾苗 245 / 溶氧 334 / 罗非鱼 166。

## 二、核心结论：QA 对与系统格式的差距

当前系统的评测格式（`eval/real_questions_v1.seed.json` → `build_real_eval_dataset.py` → `real_questions_v1.jsonl`）：

```json
{
  "id": "R001",
  "question": "…",
  "reference_answer": "…",
  "gold": [{ "doc": "crab", "ordinal": 9, "grade": 2 }],
  "species": "中华绒螯蟹",
  "category": "养殖技术",
  "expect_insufficient": false,
  "annotation_status": "ai_assisted_pending_human_review",
  "annotation_basis": "…",
  "split": "test"
}
```

标注政策（seed 文件原文）：**「所有 gold 均来自 PDF 原文对应 chunk；不把 LLM 生成的答案当 ground truth。」**

HF 问答对 `{prompt, response}` 与之对比——**三个"不能"**：

1. ❌ **`response` 不能直接当 `reference_answer`**。标注政策明确禁止未经核验的生成答案作 ground truth；
   候选池里已有可疑表述（如"pH 7.0 以下河蟹不变态不脱壳"），必须回到原文重写。
2. ❌ **不能自动生成 `gold`**。`gold[].doc + ordinal` 要求该问题能定位到**知识库中已入库文档**的具体 child chunk
   （当前别名：`crab`=DB36/T 2225、`shrimp`=DB46 海南对虾、`db32`=DB32/T 5292）。
   HF 问题指向的文档如果没入库，就无法成为合法 seed case。
3. ❌ **不能补页码/坐标**。QA 对没有"页"的概念，引用回溯链在它们身上不成立。

**四个"能"（正确用法）：**

1. ✅ **评测问题候选池**：落实方案"200 条人工核验 + 可扩展模型合成开发数据"的后半句（见第三节 pipeline）。
2. ✅ **BM25 分词验证与领域词典**：21K 条真实问题可统计高频水产词，验证 Qdrant `multilingual` 分词切分效果（ADR-0001 遗留验证项）。
3. ✅ **同义词/查询扩展表**：南美白对虾 = 凡纳滨对虾、溶氧 = 溶解氧、河蟹 = 中华绒螯蟹等，直接改善 sparse 召回。
4. ✅ **拒答测试负样本**：知识库范围外的问题 → `expect_insufficient: true` 用例，测试"证据不足"分支。

## 三、对接 pipeline：候选池 → seed cases → 正式评测集

`data/meta/qa_candidates.jsonl`（21,088 条，`status=candidate`）字段已预留对齐所需槽位
（`aligned_doc_alias` / `gold_ordinal` / `reference_answer_draft`）：

```text
qa_candidates.jsonl (candidate)
  → ① 程序对齐：每条问题检索知识库 top-k，判定能否由已入库文档支撑
      ├─ 能 → 填 aligned_doc_alias + gold_ordinal → 转 aligned
      └─ 不能 → rejected（统计"知识库覆盖边界"，反哺证据不足实验）
  → ② 生成 qa_hf_v1.seed.json（annotation_status=ai_assisted_pending_human_review）
  → ③ uv run python scripts/build_real_eval_dataset.py（解析 chunk UUID，缺块即报错）
  → ④ eval/review/ 人工复核 CSV → 定稿 hf_questions_v1.jsonl（或并入 real_questions_v2）
```

人工工作量集中在 ②：分层抽样核验（限值/用药/参数/病害/计算），对齐率、拒答率、转化率都写进论文"评测集构建"一节。

## 四、品种层候选的天然缺口（重要）

清洗后的 21,088 条里，**品种层（对虾/河蟹）只有 1,303 条（6.2%）**，且 HF 答案多数来自网络问答，
与标准文件的表述口径不一定一致。因此：

- HF 候选池主要喂**通用层**（水质、用药、池塘、鱼苗等 19,785 条）；
- **品种深度题（gold 定位到 crab/shrimp/db32 具体条款）仍以标准原文为纲**，HF 问题只作出题灵感，
  这与现有 `real_questions_v1`（70 题全部 gold 到 chunk）的路线一致。

## 五、对数据模型的一处待办（老师建议的衍生结论）

老师说语料可以是"网页和 PDF"。当前系统只接 PDF（`data/documents/<doc_id>/<version_id>/original.pdf`）。需要：

1. `kb_document_versions` 增加 `source_type`（`pdf` / `web`），网页记录**获取日期**（网页会变，版本管理价值更高）；
2. 引用位置模型支持网页锚点：PDF 用 `page + bbox`，网页用 `url + anchor_text`；
3. ingestion 增加网页正文抽取通道（trafilatura/readability → 复用结构感知切分）。

政策文件（已抓取在 `data/raw/policy/`，含五大行动通知 81 页、统计公报、病害预测预报）正好是第一批网页类语料候选。

## 六、版权

- Mxode 数据集 CC-BY-SA-4.0：毕设内部使用无碍；公开发布衍生评测集需署名并同协议共享。
- AQUA MIT：宽松。
- 建议只发布题目与核验后的 gold 及证据引用，不整体转发原始答案文本。

## 七、下一步

1. ✅ 已完成：数据集下载（走镜像）、关键词筛选、清洗、候选池落盘（字段对齐 seed 格式）。
2. 待知识库扩容后（江西/海南标准之外的通用层语料入库）：跑**对齐脚本**，统计对齐率与 rejected 率。
3. 分层人工核验 → `hf_questions_v1.seed.json` → build → review CSV → 定稿。
4. 用 21K 候选做 **BM25 分词验证报告**。
