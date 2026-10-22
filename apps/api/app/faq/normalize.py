"""Normalisation and deterministic screening for FAQ candidates.

Screening is intentionally conservative and explainable: every flag maps to a
reason a human reviewer can act on.  Nothing here can promote an entry — only
the review endpoint can change ``review_status``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

CJK_PUNCT = "，。！？；：、（）【】《》“”‘’…—·,.!?;:()[]<>\"'`~"
MIN_QUESTION_CHARS = 6
MAX_ANSWER_CHARS = 1200

# Signals that an answer makes a claim needing a strict source.
DRUG_TERMS = ("渔药", "兽药", "抗生素", "恩诺沙星", "氟苯尼考", "敌百虫", "硫酸铜", "漂白粉", "聚维酮碘", "生石灰", "剂量", "泼洒", " mg", "毫克")
UNIT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mg/l|mg·l|ppm|%|℃|度|克|千克|kg|g/l|毫升|ml|斤|亩)")
UNCERTAIN = ("不确定", "可能吧", "不知道", "仅供参考", "个人经验", "听说")
# Markers of a conditional answer that must not be served verbatim.
CONDITIONAL = ("如果", "若", "视情况", "根据实际", "分情况", "取决于")


def to_halfwidth(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def normalize_question(text: str) -> str:
    value = to_halfwidth(text or "").lower()
    value = re.sub(r"\s+", "", value)
    value = value.translate({ord(ch): None for ch in CJK_PUNCT})
    return value


def question_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def content_hash(question: str, answer: str) -> str:
    return hashlib.sha256(f"{normalize_question(question)}\n{answer.strip()}".encode()).hexdigest()


def screen(question: str, answer: str) -> list[str]:
    """Return quality flags.  Empty list means "structurally reviewable"."""
    flags: list[str] = []
    q = (question or "").strip()
    a = (answer or "").strip()

    if len(q) < MIN_QUESTION_CHARS:
        flags.append("question_too_short")
    if not a:
        flags.append("empty_answer")
    if len(a) > MAX_ANSWER_CHARS:
        flags.append("answer_too_long")
    if any(term in a for term in UNCERTAIN):
        flags.append("hedged_answer")
    if any(term in a for term in DRUG_TERMS):
        flags.append("drug_claim_needs_strict_source")
    if any(term in a for term in CONDITIONAL):
        flags.append("conditional_answer")
    if not UNIT_RE.search(a) and UNIT_RE.search(q):
        flags.append("question_has_units_answer_has_none")
    if re.search(r"[*#|]{2,}", a):
        flags.append("markup_residue")
    if a.count("。") == 0 and len(a) < 20:
        flags.append("answer_too_terse")
    return flags


def derive_topic(question: str, species: list[str]) -> str | None:
    text = question or ""
    table = {
        "水质": ("溶氧", "溶解氧", "ph", "氨氮", "亚硝酸", "水温", "透明度", "硬度", "碱度"),
        "病害": ("病", "烂鳃", "肠炎", "出血", "寄生虫", "死亡", "症状"),
        "饲料": ("饲料", "投喂", "饵料", "蛋白", "料比"),
        "苗种": ("苗", "孵化", "育苗", "幼体", "亲本", "亲虾", "亲蟹"),
        "养殖管理": ("密度", "清塘", "晒塘", "增氧", "捕捞", "运输", "混养"),
        "用药": ("用药", "渔药", "抗生素", "休药期", "残留"),
    }
    for topic, terms in table.items():
        if any(term in text.lower() for term in terms):
            return topic
    return "通用" if not species else None

# --- relevance gate -------------------------------------------------------
# Keyword filtering alone lets in "绿茶冲泡水温" and "螃蟹在地球上出现的时间"
# style rows.  A candidate must mention an aquatic organism *and* a husbandry
# context before it is worth a reviewer's time.
ORGANISM_TERMS = (
    "鱼", "虾", "蟹", "贝", "参", "藻", "蛙", "鳖", "龟", "螺", "蚌", "鳝", "鳅",
    "对虾", "罗非", "草鱼", "鲫", "鲤", "鲢", "鳙", "鲈", "石斑", "大黄鱼", "河豚",
)
CONTEXT_TERMS = (
    "养殖", "池塘", "塘口", "水质", "溶氧", "氨氮", "亚硝酸", "ph", "酸碱度", "盐度",
    "投喂", "饲料", "饵料", "苗种", "育苗", "孵化", "亲本", "病害", "发病", "症状",
    "防治", "预防", "治疗", "死亡", "增氧", "清塘", "消毒", "密度", "混养", "越冬",
    "捕捞", "运输", "尾水", "底质", "水色", "肥水", "培水", "生长", "规格", "产量",
    "饵料系数", "料比", "休药期", "渔药",
)
OFFTOPIC_MARKERS = ("冲泡", "饮用", "茶叶", "绿植", "盆栽", "人类", "地球", "宇宙", "股票")


def domain_relevant(question: str) -> tuple[bool, str]:
    text = to_halfwidth(question or "").lower()
    if any(marker in text for marker in OFFTOPIC_MARKERS):
        return False, "offtopic_marker"
    has_organism = any(term in text for term in ORGANISM_TERMS)
    has_context = any(term in text for term in CONTEXT_TERMS)
    if not has_organism:
        return False, "no_aquatic_organism"
    if not has_context:
        return False, "no_husbandry_context"
    return True, "ok"
