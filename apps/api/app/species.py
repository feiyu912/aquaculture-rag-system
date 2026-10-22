from __future__ import annotations

import re

GENERAL_SPECIES = "通用"
MAX_SPECIES = 20
SPECIES_SPLIT_RE = re.compile(r"[,，、;；/|]+")
GENERAL_ALIASES = {"通用", "全部", "不限", "通用知识", "general", "all"}
# Common aquaculture market names.  They are only canonicalized; the caller
# still decides whether the canonical species is a hard filter.
SPECIES_ALIASES = {
    "河蟹": "中华绒螯蟹",
    "绒螯蟹": "中华绒螯蟹",
    "中华绒螯蟹": "中华绒螯蟹",
    "南美白对虾": "凡纳滨对虾",
    "白对虾": "凡纳滨对虾",
    "南美白": "凡纳滨对虾",
    "凡纳滨对虾": "凡纳滨对虾",
}

# Canonical species -> surface forms seen in Chinese standards, extension
# materials and farmer questions.  Kept in one table so the alias list and the
# canonical list can never drift apart.
SPECIES_GROUPS: dict[str, tuple[str, ...]] = {
    # freshwater fish
    "草鱼": ("草鱼", "鲩鱼", "鲩"),
    "青鱼": ("青鱼", "黑鲩"),
    "鲢": ("鲢鱼", "白鲢", "鲢"),
    "鳙": ("鳙鱼", "花鲢", "胖头鱼", "鳙"),
    "鲤": ("鲤鱼", "鲤"),
    "鲫": ("鲫鱼", "鲫"),
    "鳊": ("鳊鱼", "武昌鱼", "团头鲂", "鳊"),
    "鲮": ("鲮鱼", "鲮"),
    "罗非鱼": ("罗非鱼", "非洲鲫鱼", "尼罗罗非鱼", "吉富罗非鱼"),
    "泥鳅": ("泥鳅",),
    "黄颡鱼": ("黄颡鱼", "黄颡", "昂刺鱼", "黄腊丁"),
    "鳜": ("鳜鱼", "桂鱼", "鳜"),
    "大口黑鲈": ("大口黑鲈", "加州鲈", "加州鲈鱼"),
    "乌鳢": ("乌鳢", "黑鱼", "生鱼"),
    "鳗鲡": ("鳗鲡", "鳗鱼"),
    "鲟": ("鲟鱼", "杂交鲟", "鲟"),
    "虹鳟": ("虹鳟", "虹鳟鱼"),
    "长吻鮠": ("长吻鮠", "江团"),
    "翘嘴鲌": ("翘嘴鲌", "翘嘴", "白鱼"),
    "黄鳝": ("黄鳝", "鳝鱼"),
    # marine fish
    "大黄鱼": ("大黄鱼", "黄花鱼"),
    "石斑鱼": ("石斑鱼", "珍珠龙胆", "斜带石斑鱼", "青斑"),
    "大菱鲆": ("大菱鲆", "多宝鱼"),
    "牙鲆": ("牙鲆",),
    "半滑舌鳎": ("半滑舌鳎", "舌鳎"),
    "卵形鲳鲹": ("卵形鲳鲹", "金鲳", "金鲳鱼"),
    "海鲈": ("海鲈", "花鲈"),
    # crustaceans
    "凡纳滨对虾": ("凡纳滨对虾", "南美白对虾", "白对虾", "南美白"),
    "斑节对虾": ("斑节对虾", "草虾", "黑虎虾"),
    "日本对虾": ("日本对虾", "车虾", "花虾"),
    "中国对虾": ("中国对虾", "东方对虾", "明虾"),
    "罗氏沼虾": ("罗氏沼虾", "淡水长臂大虾", "罗氏虾"),
    "日本沼虾": ("日本沼虾", "青虾"),
    "克氏原螯虾": ("克氏原螯虾", "小龙虾", "淡水小龙虾"),
    "中华绒螯蟹": ("中华绒螯蟹", "河蟹", "绒螯蟹", "大闸蟹"),
    "三疣梭子蟹": ("三疣梭子蟹", "梭子蟹"),
    "拟穴青蟹": ("拟穴青蟹", "青蟹", "膏蟹", "锯缘青蟹"),
    # molluscs / echinoderms / algae / reptiles / amphibians
    "栉孔扇贝": ("栉孔扇贝",),
    "海湾扇贝": ("海湾扇贝",),
    "虾夷扇贝": ("虾夷扇贝",),
    "太平洋牡蛎": ("太平洋牡蛎", "牡蛎", "生蚝"),
    "皱纹盘鲍": ("皱纹盘鲍", "鲍鱼"),
    "仿刺参": ("仿刺参", "刺参", "海参"),
    "海带": ("海带",),
    "紫菜": ("紫菜", "条斑紫菜", "坛紫菜"),
    "裙带菜": ("裙带菜",),
    "中华鳖": ("中华鳖", "甲鱼", "鳖"),
    "牛蛙": ("牛蛙",),
}

for _canonical, _forms in SPECIES_GROUPS.items():
    SPECIES_ALIASES.setdefault(_canonical, _canonical)
    for _form in _forms:
        SPECIES_ALIASES.setdefault(_form, _canonical)


def canonical_species(value: str) -> str:
    cleaned = _clean(value)
    return SPECIES_ALIASES.get(cleaned.lower(), SPECIES_ALIASES.get(cleaned, cleaned))


def _clean(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def parse_species(raw: str | None) -> list[str]:
    """Normalize a free-text species field.

    Empty input means general knowledge. Specific species win over the reserved
    "通用" marker so a document is never both general and species-specific.
    """
    if raw is None or not raw.strip():
        return [GENERAL_SPECIES]

    result: list[str] = []
    seen: set[str] = set()
    for part in SPECIES_SPLIT_RE.split(raw):
        value = _clean(part)
        if not value:
            continue
        if value.lower() in GENERAL_ALIASES:
            value = GENERAL_SPECIES
        else:
            value = canonical_species(value)
        if len(value) > 32:
            raise ValueError("品种名称过长")
        if value not in seen:
            seen.add(value)
            result.append(value)

    if not result:
        return [GENERAL_SPECIES]
    specific = [value for value in result if value != GENERAL_SPECIES]
    if specific:
        return specific[:MAX_SPECIES]
    return [GENERAL_SPECIES]


def normalize_species_list(values: list[str] | None) -> list[str]:
    if not values:
        return [GENERAL_SPECIES]
    return parse_species("、".join(str(value) for value in values))


def species_text(values: list[str] | None) -> str:
    return "、".join(normalize_species_list(values))


def detect_species(question: str, options: list[str]) -> str | None:
    """Return a unique species mentioned in the question.

    Ambiguous questions (two or more species) intentionally return None: a hard
    filter would hide evidence instead of letting the answer discuss both.
    """
    text = question.lower()
    hits: list[str] = []
    for option in sorted(
        {item for item in options if item != GENERAL_SPECIES}, key=len, reverse=True
    ):
        if not option:
            continue
        if option.lower() in text:
            hits.append(option)
            continue
        aliases = [alias for alias, canonical in SPECIES_ALIASES.items() if canonical == option]
        if any(alias.lower() in text for alias in aliases):
            hits.append(option)
            continue
        # "对虾" should select "凡纳滨对虾" when that is the only known species.
        # If several species share the suffix, leave the query unfiltered.
        if any(option.lower()[start:] in text for start in range(1, len(option) - 1)):
            hits.append(option)
    if len(hits) != 1:
        return None
    return hits[0]


def species_in_text(text: str) -> list[str]:
    """All canonical species mentioned in free text (longest alias wins).

    Unlike :func:`detect_species` this does not need a candidate list, so it can
    be used to check whether evidence is applicable to the question even when
    the mentioned species has no documents yet.
    """
    haystack = (text or "").lower()
    if not haystack:
        return []
    found: dict[str, str] = {}
    for alias in sorted(SPECIES_ALIASES, key=len, reverse=True):
        canonical = SPECIES_ALIASES[alias]
        if canonical in found:
            continue
        if alias.lower() in haystack:
            found[canonical] = alias
    return list(found)


def species_applicable(document_species: list[str] | None, question_species: set[str]) -> bool:
    """True when a document may answer a question about ``question_species``.

    Unknown or ``通用`` documents are treated as applicable; a species-specific
    document only applies when the species sets intersect.  This is the check
    that stops a Penaeus standard from answering a koi-herpesvirus question.
    """
    if not question_species:
        return True
    normalized = set(normalize_species_list(document_species))
    if not normalized or GENERAL_SPECIES in normalized:
        return True
    return bool(normalized & question_species)
