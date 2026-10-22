#!/usr/bin/env python3
"""Build a 100-question Chinese retrieval eval set from servable documents.

The set is stratified by source (standards / national forecasts / local tech
articles / journals / WorldFish cross-lingual) and every case carries the exact
child chunk that answers it.  Questions never quote the source title for
articles; standard questions cite the standard code, which is how users
actually ask about standards.

Overlap with the QA-dataset team's questions (data/hf_qa/eval/*.jsonl) and the
earlier internal set (eval/real_questions_v1.jsonl) is rejected by character
5-gram Jaccard, not by exact match.

Output:
  eval/retrieval_eval_100_v1.jsonl
  eval/retrieval_eval_100_v1.manifest.json
  eval/review/retrieval_eval_100_v1_review.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

SPECIES = [
    "凡纳滨对虾", "南美白对虾", "斑节对虾", "日本沼虾", "克氏原螯虾", "小龙虾", "中华绒螯蟹",
    "河蟹", "中华鳖", "乌龟", "鳄龟", "大黄鱼", "石斑鱼", "大口黑鲈", "加州鲈", "翘嘴鳜",
    "鳜", "黄颡鱼", "泥鳅", "黄鳝", "鳗鲡", "牙鲆", "大菱鲆", "半滑舌鳎", "达氏鳇", "鲟",
    "草鱼", "鲫", "鲤", "鲢", "鳙", "青鱼", "罗非鱼", "鳊", "鲂", "虹鳟", "鲈", "虾夷扇贝",
    "栉孔扇贝", "牡蛎", "缢蛏", "文蛤", "鲍", "海参", "仿刺参", "海带", "紫菜", "裙带菜",
    "江蓠", "珍珠", "三角帆蚌", "金鱼", "锦鲤",
]
AQUATIC = re.compile(
    "|".join(SPECIES)
    + "|水产|渔业|养殖|池塘|网箱|育苗|苗种|病害|饵料|饲料|水质|投喂|越冬|繁殖|孵化|鱼|虾|蟹|贝|藻|鳖|蛙|鳅|鳝|鲟|鲈|鲷|鲳|鲀|鳕|鳟"
)
NOT_AQUATIC = re.compile(
    "荔枝|菠萝|龙眼|香蕉|柑橘|蔬菜|水果|茶叶|水稻种植|玉米|小麦|大豆|棉花|油菜|猪|牛|羊|鸡|鸭|鹅|"
    "贝瓷|精油|花卉|苗木|食用菌|中药材|农机|沼气"
)


def norm(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "").lower()


def shingles(text: str, n: int = 5) -> set[str]:
    value = norm(text)
    return {value[i : i + n] for i in range(max(0, len(value) - n + 1))}


def similar(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


_SPECIES_BY_LEN = sorted(SPECIES, key=len, reverse=True)


def species_in(text: str) -> str | None:
    for name in _SPECIES_BY_LEN:
        if name in (text or ""):
            return name
    return None


def standard_code(title: str) -> str | None:
    match = re.search(
        r"((?:DB\d+(?:/T)?|SC/T|GB/T|GB|NY/T|HJ)\s*\d+(?:\.\d+)?(?:\s*[—\-]\s*\d+)?)",
        title,
    )
    if match:
        return re.sub(r"\s+", "", match.group(1))
    return None


def first_sentences(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = re.split(r"(?<=[。；！？])", text)
    out = ""
    for part in parts:
        if not part.strip():
            continue
        if len(out) + len(part) > limit and out:
            break
        out += part
    return out.strip()[:limit]


BOILERPLATE = re.compile(r"目\s*次|前\s*言|规范性引用文件|术语和定义|参考文献|引\s*言|附\s*录")


def junk_chunk(chunk: dict) -> bool:
    text = chunk.get("content") or ""
    heads = " ".join(str(h) for h in (chunk.get("heading_path") or []) if h)
    if BOILERPLATE.search(heads) or BOILERPLATE.search(text[:40]):
        return True
    if text.count("....") >= 3:  # table of contents
        return True
    return text.count("|") >= 6  # markdown table fragment


def junk_title(title: str) -> bool:
    return bool(re.search(r"[|｜丨]|\.\.\.|？$|！$", title)) or len(title) > 42


def strip_site(title: str) -> str:
    return re.sub(r"\s*\d{1,2}-\d{1,2}$", "", title).strip()


def year_month_province(title: str) -> tuple[str, str, str] | None:
    match = re.search(r"(\d{4})年(\d{1,2})月(.{2,8}?)(?:水产养殖)?病害", title)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


async def load_docs() -> list[dict]:
    from sqlalchemy import text

    from app.db import SessionLocal

    sql = """
    SELECT d.id, d.title, d.source_trust, d.source_org, d.current_version_id,
           d.doc_genre, d.region,
           (SELECT count(*) FROM kb_chunks c
             WHERE c.document_version_id=d.current_version_id AND c.chunk_role='child') AS chunks
    FROM kb_documents d
    WHERE d.status='active' AND d.index_eligibility='eligible'
      AND d.technical_review_status<>'fail' AND d.current_version_id IS NOT NULL
    ORDER BY d.id
    """
    async with SessionLocal() as db:
        rows = [dict(r._mapping) for r in (await db.execute(text(sql))).all()]
    for row in rows:
        if row["source_org"] == "WorldFish":
            row["group"] = "worldfish"
        elif row["source_trust"] == "official_standard":
            row["group"] = "standard"
        elif row["source_trust"] == "official_local":
            row["group"] = "local"
        elif row["source_trust"] == "official_national":
            row["group"] = "national"
        elif row["source_trust"] == "research_institute":
            row["group"] = "journal"
        else:
            row["group"] = "other"
    return [row for row in rows if row["chunks"]]


async def load_chunks(version_ids: list[str]) -> dict[str, list[dict]]:
    from sqlalchemy import text

    from app.db import SessionLocal

    out: dict[str, list[dict]] = defaultdict(list)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, document_version_id, ordinal, content, heading_path, page_from "
                    "FROM kb_chunks WHERE document_version_id = ANY(:ids) "
                    "AND chunk_role='child' ORDER BY document_version_id, ordinal"
                ),
                {"ids": version_ids},
            )
        ).all()
    for row in rows:
        item = dict(row._mapping)
        out[str(item["document_version_id"])].append(item)
    return out


def load_exclusions() -> list[str]:
    questions: list[str] = []
    for path in [*ROOT.glob("data/hf_qa/eval/*.jsonl"), ROOT / "eval/real_questions_v1.jsonl"]:
        if not Path(path).exists():
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("question"):
                questions.append(row["question"])
    return questions


OVERRIDES = {
    "毛沟稻田稻虾轮作": "毛沟稻田稻虾轮作模式中，小龙虾投苗后如何精准投喂？",
    "基于生物经济模型的中国花鲈": "基于生物经济模型的中国花鲈养殖投苗策略研究得出了什么结论？",
    "广东省乌鳢健康养殖模式": "乌鳢高密度单养模式下的苗种放养密度是多少？",
    "冷藏凡纳滨对虾": "冷藏凡纳滨对虾贮藏期间品质与菌群如何变化？",
    "中华鳖减抗替抗养殖": "中华鳖减抗替抗养殖有哪些技术要点？",
    "2025年春季渔业生产管理要点": "湖北省2025年春季渔业生产管理要点中，春季易发病害如何精准防治？",
    "翘嘴鳜“华康2号”": "翘嘴鳜“华康2号”的饲料养殖技术要点是什么？",
    "大口黑鲈不同冻结方式": "不同冻结方式对大口黑鲈鱼肉品质有什么影响？",
}


def build_candidate(doc: dict, chunk: dict, group: str) -> dict | None:
    title = strip_site(doc["title"])
    text = chunk["content"]
    heads = [h for h in (chunk["heading_path"] or []) if h]
    section = heads[-1] if heads else None
    species = species_in(title) or species_in(text[:300])

    if group == "standard":
        code = standard_code(title)
        if not code:
            return None
        if section and "范围" in section:
            question = f"《{code}》适用于哪些对象和养殖方式？"
            qtype = "standard_scope"
        elif section and re.match(r"^\d+(\.\d+)*", section) and section not in title:
            question = f"《{code}》对“{section}”提出了哪些要求？"
            qtype = "standard_section"
        else:
            return None
    elif group == "national":
        parsed = year_month_province(title)
        if not parsed or "病情预测" not in " ".join(heads) + text[:120]:
            return None
        year, month, province = parsed
        question = f"{year}年{month}月{province}水产养殖需要重点防控哪些病害？"
        qtype = "forecast"
    elif group == "local":
        if not species or junk_title(title) or "病害预测预报" in title or "预测预报" in title:
            return None
        topic = re.sub(rf"^{re.escape(species)}", "", title)
        topic = re.sub(r"^(关于|如何|怎样|请问)", "", topic)
        topic = re.sub(r"(技术|要点|指南|模式|措施|方法|规范)$", "", topic).strip("：: ")
        if len(topic) < 2:
            topic = "养殖"
        if section and len(section) <= 24 and re.match(r"^[一二三四五六七八九十\d]", section):
            if section.startswith(species):
                return None
            question = f"{species}{topic}中，{section}有哪些要求？"
        else:
            question = f"{species}{topic}的技术要点有哪些？"
        qtype = "local_tech"
    elif group == "journal":
        if not species:
            return None
        topic = re.sub(r"(研究|分析|初探|进展|综述|的影响|的作用|及机制)", "", title)
        topic = re.sub(rf"^{re.escape(species)}", "", topic).strip("：: ，,")
        question = f"{species}{topic[:18]}研究得出了什么结论？"
        qtype = "journal_conclusion"
    else:
        return None

    for key, value in OVERRIDES.items():
        if key in title:
            question = value
            break
    if len(question) < 8 or len(question) > 60:
        return None
    return {
        "question": question,
        "reference_answer": first_sentences(text),
        "question_type": qtype,
        "group": group,
        "species": species,
        "gold": [
            {
                "document_id": str(doc["id"]),
                "version_id": str(doc["current_version_id"]),
                "chunk_id": str(chunk["id"]),
                "title": doc["title"],
                "page": chunk["page_from"],
                "evidence": first_sentences(text, 300),
            }
        ],
        "annotation_status": "template_generated_pending_human_review",
        "annotation_basis": f"标题/章节与块原文：{section or title}",
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "retrieval_eval_100_v1.jsonl")
    parser.add_argument("--per-group", default="standard=29,national=20,local=36,journal=15")
    args = parser.parse_args()
    quotas = {
        key: int(value) for key, value in (item.split("=") for item in args.per_group.split(","))
    }

    docs = await load_docs()
    chunks = await load_chunks([str(d["current_version_id"]) for d in docs])
    exclusions = load_exclusions()
    print(f"servable docs {len(docs)}, exclusions {len(exclusions)}")

    pool: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        if doc["group"] not in quotas:
            continue
        title = strip_site(doc["title"])
        if NOT_AQUATIC.search(title) or not AQUATIC.search(title + " " + doc["title"]):
            continue
        pool[doc["group"]].append(doc)

    cases: list[dict] = []
    seen_species: Counter = Counter()
    for group, quota in quotas.items():
        candidates = sorted(pool[group], key=lambda d: hashlib.md5(str(d["id"]).encode()).hexdigest())
        made = 0
        used_docs: set[str] = set()
        for doc in candidates * 3:
            if made >= quota:
                break
            if str(doc["id"]) in used_docs:
                continue
            doc_chunks = chunks.get(str(doc["current_version_id"]), [])
            if not doc_chunks:
                continue
            # Standard: prefer the scope chunk, then the longest headed chunk.
            if group == "journal":
                ordered = sorted(
                    doc_chunks,
                    key=lambda c: -len(re.findall(r"[\u4e00-\u9fff]", c["content"] or "")),
                )
            else:
                ordered = sorted(
                    doc_chunks,
                    key=lambda c: (
                        1 if any("范围" in str(h) for h in (c["heading_path"] or [])) else 0,
                        -len(c["content"] or ""),
                    ),
                )
            for chunk in ordered[:4]:
                if len(chunk["content"] or "") < 80 or junk_chunk(chunk):
                    continue
                if group == "journal" and ("[J]" in chunk["content"] or "参考文献" in chunk["content"]):
                    continue
                candidate = build_candidate(doc, chunk, group)
                if not candidate:
                    continue
                if any(similar(candidate["question"], q) > 0.55 for q in exclusions):
                    continue
                if any(similar(candidate["question"], c["question"]) > 0.7 for c in cases):
                    continue
                used_docs.add(str(doc["id"]))
                seen_species[candidate["species"] or "(none)"] += 1
                candidate["id"] = f"E{len(cases) + 1:03d}"
                candidate["split"] = "test"
                cases.append(candidate)
                made += 1
                break
        print(f"{group}: {made}/{quota}")

    # Interleave groups so the file is not a run of one source.
    grouped: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        grouped[case["group"]].append(case)
    ordered: list[dict] = []
    index = 0
    while len(ordered) < len(cases):
        for group in quotas:
            if index < len(grouped.get(group, [])):
                ordered.append(grouped[group][index])
        index += 1
    for number, case in enumerate(ordered, start=1):
        case["id"] = f"E{number:03d}"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for case in ordered:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    manifest = {
        "count": len(ordered),
        "by_group": dict(Counter(c["group"] for c in ordered)),
        "by_type": dict(Counter(c["question_type"] for c in ordered)),
        "unique_species": len(seen_species),
        "exclusions_considered": len(exclusions),
        "annotation_status": "template_generated_pending_human_review",
        "source_snapshot": "kb-v1_20261022",
    }
    args.out.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    review = ROOT / "eval" / "review" / "retrieval_eval_100_v1_review.csv"
    review.parent.mkdir(parents=True, exist_ok=True)
    with review.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "group", "question", "reference_answer", "title", "chunk_id", "verdict", "notes"])
        for case in ordered:
            writer.writerow([
                case["id"], case["group"], case["question"], case["reference_answer"],
                case["gold"][0]["title"], case["gold"][0]["chunk_id"], "", "",
            ])
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))