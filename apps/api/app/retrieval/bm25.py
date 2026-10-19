from __future__ import annotations

import re
import zlib

import jieba
from qdrant_client import models

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
ALNUM_RE = re.compile(r"[a-z0-9]+(?:[.%-][a-z0-9]+)*")

# Domain terms that general-purpose Chinese tokenizers often split incorrectly.
CUSTOM_TERMS = [
    "中华绒螯蟹",
    "凡纳滨对虾",
    "南美白对虾",
    "罗氏沼虾",
    "克氏原螯虾",
    "水产养殖",
    "溶解氧",
    "亚硝酸盐",
    "氨氮",
    "非离子氨",
    "总氨氮",
    "酸碱度",
    "盐度",
    "水温",
    "透明度",
    "蜕壳",
    "脱壳",
    "投喂",
    "饵料系数",
    "饲料转化率",
    "养殖密度",
    "增氧机",
    "底质",
    "弧菌",
    "白斑综合征",
    "肝胰腺",
    "应激",
    "消毒",
    "生石灰",
]

STOPWORDS = {
    "的",
    "了",
    "和",
    "与",
    "及",
    "在",
    "是",
    "为",
    "对",
    "中",
    "上",
    "下",
    "等",
    "可",
    "以",
    "有",
    "无",
    "不",
    "也",
    "都",
    "就",
    "而",
    "或",
    "其",
    "这",
    "那",
    "一个",
    "一种",
    "什么",
    "怎么",
    "如何",
    "以及",
    "进行",
    "需要",
    "可以",
    "应该",
    "我们",
    "你们",
    "他们",
    "它",
    "这个",
    "那个",
    "哪些",
    "多少",
}

for _term in CUSTOM_TERMS:
    jieba.add_word(_term, freq=10000)


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("\u3000", " ")
    tokens: list[str] = []
    for match in re.finditer(r"[\u4e00-\u9fff]+|[a-z0-9]+(?:[.%-][a-z0-9]+)*", text):
        piece = match.group(0)
        if CJK_RE.fullmatch(piece):
            tokens.extend(jieba.lcut(piece, cut_all=False))
        else:
            tokens.append(piece)
    result: list[str] = []
    for token in tokens:
        token = token.strip()
        if not token or token in STOPWORDS:
            continue
        if CJK_RE.fullmatch(token) and len(token) == 1:
            continue
        result.append(token)
    return result


def _index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


class BM25SparseEncoder:
    """BM25 term weights stored as Qdrant sparse vectors.

    Qdrant's server-side BM25 inference requires an inference service that is not
    enabled in the local OSS image, so the client computes the BM25 weights and
    Qdrant applies IDF via the sparse-vector `modifier=idf`.
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75, avg_len: float = 300.0) -> None:
        self.k1 = k1
        self.b = b
        self.avg_len = max(avg_len, 1.0)

    def document_vector(self, text: str) -> models.SparseVector:
        tokens = tokenize(text)
        if not tokens:
            return models.SparseVector(indices=[], values=[])
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        length = len(tokens)
        norm = self.k1 * (1.0 - self.b + self.b * length / self.avg_len)
        values: dict[int, float] = {}
        for token, count in counts.items():
            weight = count * (self.k1 + 1.0) / (count + norm)
            idx = _index(token)
            values[idx] = values.get(idx, 0.0) + weight
        return models.SparseVector(
            indices=sorted(values),
            values=[values[i] for i in sorted(values)],
        )

    def query_vector(self, text: str) -> models.SparseVector:
        tokens = tokenize(text)
        if not tokens:
            return models.SparseVector(indices=[], values=[])
        unique = sorted(set(tokens))
        values: dict[int, float] = {}
        for token in unique:
            idx = _index(token)
            values[idx] = values.get(idx, 0.0) + 1.0
        return models.SparseVector(
            indices=sorted(values),
            values=[values[i] for i in sorted(values)],
        )

    def config(self) -> dict:
        return {"k1": self.k1, "b": self.b, "avg_len": self.avg_len, "tokenizer": "jieba"}
