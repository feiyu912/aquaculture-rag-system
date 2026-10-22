"""Entity and metadata checks that run before an answer may be generated.

The lexical sufficiency gate cannot tell a real standard from a plausible-looking
code, or a 2027 forecast from a 2025 one.  These checks compare what the user
actually named (standard code, year/month, province, species, numeric ask)
against the catalogue, and refuse with a concrete reason when the entity does
not exist or contradicts the retrieved document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.retrieval.sufficiency import Sufficiency

CODE_RE = re.compile(
    r"(?<![0-9A-Za-z])((?:DB\d{2,6}(?:/T)?|SC/T|GB/T|GB|NY/T|HJ|DB\d+)\s*\d{3,6}"
    r"(?:\.\d+)?\s*[—\-－]\s*\d{4})(?!\d)"
)
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年")
MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月")
PROVINCES = (
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省", "黑龙江省",
    "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省", "河南省",
    "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省", "重庆市", "四川省", "贵州省",
    "云南省", "西藏自治区", "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",
    "台湾省", "香港特别行政区", "澳门特别行政区",
)
NUMERIC_ASK_RE = re.compile(r"多少|几|数值|比例|含量|浓度|限量|用量|亩产|产量")
VALIDITY_ASK_RE = re.compile(r"是否(?:现行|有效|废止)|现行有效|还有效|失效|废止|作废")


def normalize_code(value: str) -> str:
    # Catalogue titles and user questions disagree on spaces and dash glyphs
    # ("DB22/T 3310-2021" vs "DB22/T3310—2021"); compare a canonical form.
    return re.sub(r"\s+", "", value.upper()).replace("－", "-").replace("—", "-").replace("–", "-")


def extract_codes(question: str) -> list[str]:
    return list(dict.fromkeys(normalize_code(m.group(1)) for m in CODE_RE.finditer(question)))


def extract_year(question: str) -> int | None:
    match = YEAR_RE.search(question)
    return int(match.group(1)) if match else None


def extract_month(question: str) -> int | None:
    match = MONTH_RE.search(question)
    if not match:
        return None
    month = int(match.group(1))
    return month if 1 <= month <= 12 else None


def extract_province(question: str) -> str | None:
    for name in sorted(PROVINCES, key=len, reverse=True):
        if name in question:
            return name
    # common short forms
    for short, full in (("内蒙", "内蒙古自治区"), ("广西", "广西壮族自治区"), ("宁夏", "宁夏回族自治区"),
                        ("新疆", "新疆维吾尔自治区"), ("西藏", "西藏自治区")):
        if short in question:
            return full
    return None


@dataclass
class StandardDoc:
    code: str
    title: str
    region: str | None = None
    effective_year: int | None = None
    species: list[str] = field(default_factory=list)
    status: str | None = None


@dataclass
class ForecastDoc:
    year: int
    month: int
    province: str | None
    title: str


@dataclass
class Violation:
    reason: str
    detail: str


def parse_standard(title: str) -> StandardDoc | None:
    match = CODE_RE.search(title or "")
    if not match:
        return None
    return StandardDoc(code=normalize_code(match.group(1)), title=title)


def parse_forecast(title: str) -> ForecastDoc | None:
    match = re.search(r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月(.{2,10}?)(?:水产养殖)?病害(?:预测)?预报", title or "")
    if not match:
        return None
    province = next((p for p in PROVINCES if p in match.group(3)), None)
    return ForecastDoc(int(match.group(1)), int(match.group(2)), province, title)


def evaluate(
    question: str,
    *,
    standards: list[StandardDoc],
    forecasts: list[ForecastDoc],
    doc_region: str | None = None,
    doc_species: list[str] | None = None,
    doc_title: str = "",
    query_species: list[str] | None = None,
    evidence_text: str = "",
) -> Violation | None:
    """Return the first hard contradiction, or None when the checks pass."""
    codes = extract_codes(question)
    year = extract_year(question)
    province = extract_province(question)

    if codes:
        by_code = {doc.code: doc for doc in standards}
        for code in codes:
            doc = by_code.get(code)
            if doc is None:
                return Violation("standard_not_found", code)
            if doc.status and any(word in doc.status for word in ("废止", "失效", "作废")):
                return Violation("standard_not_current", f"{code} status={doc.status}")
            if (
                year
                and doc.effective_year
                and re.search(r"实施|施行|生效", question)
                and year != doc.effective_year
            ):
                return Violation(
                    "effective_date_mismatch",
                    f"asked {year}, catalogue {doc.effective_year}",
                )
            if province and doc.region and province not in doc.region and doc.region not in province:
                return Violation("region_mismatch", f"asked {province}, document {doc.region}")
            if (
                asked_species := [s for s in (query_species or []) if s and s != "通用"]
            ) and evidence_text:
                haystack = f"{doc_title} {evidence_text}"
                if not any(species in haystack for species in asked_species):
                    return Violation(
                        "species_not_in_evidence",
                        f"asked {asked_species}, not in document or evidence",
                    )
            asked_species = [s for s in (query_species or []) if s and s != "通用"]
            doc_species = [s for s in (doc.species or []) if s and s != "通用"]
            if asked_species and doc_species and not set(asked_species) & set(doc_species):
                return Violation(
                    "species_mismatch", f"asked {asked_species}, document {doc_species}"
                )

    if re.search(r"预报|预测", question) and (year or province):
        month = extract_month(question)
        hits = [
            doc
            for doc in forecasts
            if (year is None or doc.year == year)
            and (month is None or doc.month == month)
            and (province is None or doc.province == province)
        ]
        if not hits:
            detail = f"{year or '?'}-{month or '?'} {province or '?'}"
            return Violation("forecast_not_found", detail)

    contextual = bool(codes) or bool(re.search(r"预报|预测", question))
    if (
        contextual
        and province
        and doc_region
        and province not in doc_region
        and doc_region not in province
    ):
        return Violation("region_mismatch", f"asked {province}, top document {doc_region}")

    asked_species = [s for s in (query_species or []) if s and s != "通用"]
    known = [s for s in (doc_species or []) if s and s != "通用"]
    if asked_species and known and not set(asked_species) & set(known):
        return Violation("species_mismatch", f"asked {asked_species}, top document {known}")

    if re.search(r"(全国|全球|中国|我国|全省|全市|全县)", question) and re.search(
        r"总量|总产量|总产值|销量|产值|碳排放|统计数据", question
    ):
        noun = re.search(r"碳排放|总产量|总产值|销量|产值|统计数据", question)
        if noun and noun.group(0) not in evidence_text:
            return Violation("aggregate_stat_not_in_corpus", noun.group(0))

    if re.search(r"某(?:县|市|区|镇|村|公司|企业|品牌|养殖户|农户)", question) and re.search(
        r"结果|检查|通报|名单|数据|销量|产量|公告", question
    ):
        return Violation("underspecified_entity", "placeholder entity with a data request")

    if NUMERIC_ASK_RE.search(question) and not re.search(r"\d", evidence_text):
        return Violation("no_numeric_evidence", "question asks for a number, evidence has none")

    if VALIDITY_ASK_RE.search(question):
        if not doc_region and not doc_species and not codes:
            return None
        # Validity can only be asserted when the catalogue stores a status.
        doc = next((d for d in standards if d.code in codes), None) if codes else None
        if doc is not None and not doc.status:
            return Violation("validity_unverified", doc.code)
    return None


def apply_gate(gate: Sufficiency, violation: Violation | None) -> Sufficiency:
    if violation is None or not gate.sufficient:
        return gate
    return Sufficiency(
        False,
        violation.reason,
        gate.query_terms,
        gate.matched_terms,
        gate.matched_weight,
        gate.total_weight,
        gate.coverage,
        gate.best_index,
        gate.missing_terms,
    )

async def apply_entity_checks(db, question, query_ir, evidence, gate: Sufficiency) -> Sufficiency:
    """Load the small catalogue slices the question needs, then apply the gate."""
    from sqlalchemy import text

    if not gate.sufficient or not evidence:
        return gate
    codes = extract_codes(question)
    forecast = bool(re.search(r"预报|预测", question))
    numeric = bool(NUMERIC_ASK_RE.search(question))
    placeholder = bool(
        re.search(r"某(?:县|市|区|镇|村|公司|企业|品牌|养殖户|农户)", question)
        and re.search(r"结果|检查|通报|名单|数据|销量|产量|公告", question)
    )
    aggregate = bool(
        re.search(r"(全国|全球|中国|我国|全省|全市|全县)", question)
        and re.search(r"总量|总产量|总产值|销量|产值|碳排放|统计数据", question)
    )
    if not (codes or forecast or numeric or placeholder or aggregate):
        return gate

    standards: list[StandardDoc] = []
    forecasts: list[ForecastDoc] = []
    if codes:
        rows = (
            await db.execute(
                text(
                    "SELECT title, region, effective_date, species, "
                    "metadata->>'document_status' FROM kb_documents "
                    "WHERE status='active' AND index_eligibility='eligible' "
                    "AND source_trust='official_standard'"
                )
            )
        ).all()
        for title, region, effective, species, status in rows:
            doc = parse_standard(title)
            if doc is None:
                continue
            doc.region = region
            doc.effective_year = int(str(effective)[:4]) if effective else None
            doc.species = list(species or [])
            doc.status = status
            standards.append(doc)
    if forecast:
        titles = (
            await db.execute(
                text(
                    "SELECT title FROM kb_documents WHERE status='active' "
                    "AND index_eligibility='eligible' AND title LIKE '%病害预测预报%'"
                )
            )
        ).scalars().all()
        forecasts = [doc for title in titles if (doc := parse_forecast(title))]

    doc_region: str | None = None
    doc_species: list[str] = []
    if evidence[0].document_id is not None:
        row = (
            await db.execute(
                text("SELECT region, species FROM kb_documents WHERE id=:id"),
                {"id": evidence[0].document_id},
            )
        ).first()
        if row is not None:
            doc_region, doc_species = row[0], list(row[1] or [])

    evidence_text = "\n".join(
        f"{item.content} {item.quote}" for item in evidence[:3]
    )
    violation = evaluate(
        question,
        standards=standards,
        forecasts=forecasts,
        doc_region=doc_region,
        doc_species=doc_species,
        doc_title=evidence[0].title,
        query_species=list(getattr(query_ir, "species", []) or []),
        evidence_text=evidence_text,
    )
    return apply_gate(gate, violation)
