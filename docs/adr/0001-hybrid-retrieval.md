# ADR-0001：混合检索采用 Dense + BM25 + RRF

| 项 | 内容 |
|---|---|
| 状态 | 已接受 |
| 日期 | 2026-10-19 |
| 决策者 | 项目组 |
| 相关文档 | [技术方案](../technical-plan.md) 第 4 节 D1、第 7 节 |

## 背景

系统需要满足学校对“混合检索”的要求，同时保证论文中的算法定义准确、实验可复现。旧方案写成“BGE-M3 同时输出 Dense 和 Sparse，利用 Qdrant 实现 Dense + BM25 混合召回”，把 BGE-M3 Sparse 与 BM25 混为一谈。

## 决策

主线采用：

```text
BGE-M3 Dense + Qdrant BM25 → RRF → BGE-Reranker-v2-m3
```

- Dense：BGE-M3，1024 维，Cosine。
- Sparse：Qdrant 原生 BM25，`modifier=idf`，`multilingual` 分词器。
- 融合：RRF，`k=60`。
- 重排：BGE-Reranker-v2-m3。

BGE-M3 Sparse 作为额外对照实验，不进入正式链路。

## 备选方案

| 方案 | 不采用的原因 |
|---|---|
| BGE-M3 Dense + Sparse | Sparse 是学习词项权重，不是 BM25；无法直接声称满足“BM25 混合检索” |
| Elasticsearch BM25 + Qdrant Dense | 多引入一个组件与一套运维，本科项目收益不足 |
| 纯 Dense | 缺少关键词精确匹配，无法做混合检索消融 |
| Qdrant 原生 RRF 之外再手写融合 | 生产可用原生；应用侧只保留参考实现用于核对 |

## 后果

- 必须做中文术语切分测试；`multilingual` 分词器对水产专有名词的效果需验证。
- 两路召回分别记录候选、排名与耗时，便于 E1 消融。
- 集合需要同时配置 dense 与 sparse 向量；模型或分词器变化时全量重建。
- 论文中明确区分“学习型稀疏表示”和“BM25”，不混用术语。