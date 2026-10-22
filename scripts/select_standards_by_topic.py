#!/usr/bin/env python3
"""Select local (DB) aquaculture standards by *topic*, then download them.

The pilot in ``download_standards.py`` sampled DB standards at random.  This
helper ranks the same catalogue (``data/reports/standards_catalog.json``) by
six topical themes, prefers the newest editions and the widest provincial
spread, and can download the shortlist through the existing public endpoints.

Only *new* files: the download half reuses ``download_standards``' throttle,
PDF probe and ``data_items`` insert; nothing in the existing scripts changes.

Selection is deterministic: the same catalogue plus the same quota yields the
same shortlist.  Titles that merely contain an aquatic character but are not
aquaculture (ceramics, cuisine, cold-chain, lake meteorology, ...) are dropped
by ``NOISE_RE`` plus a small reviewed exclusion set.

Usage (from ``apps/api``)::

    uv run python ../../scripts/select_standards_by_topic.py --select-only
    uv run python ../../scripts/select_standards_by_topic.py --download
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from download_standards import (  # noqa: E402
    PLATFORMS,
    UA,
    Throttle,
    _existing_urls,
    _get,
    _insert_item,
    _pdf_stats,
)

CST = ZoneInfo("Asia/Shanghai")
INBOX = ROOT / "data" / "inbox"
DEFAULT_SELECTION = ROOT / "data" / "reports" / "standards_selection2.json"
DEFAULT_REPORT = ROOT / "data" / "reports" / "download_standards2.json"

# ---------------------------------------------------------------------------
# Topic model
# ---------------------------------------------------------------------------
# Priority for *shortlisting* is 水质 > 苗种 > 饲料 > 养殖管理 > 病害 > 尾水.
# For attribution we match the most specific theme first (尾水/病害/水质), so a
# title such as "水产养殖尾水监测" is not swallowed by the generic 养殖 theme.
THEME_ORDER = ["水质底质", "苗种繁育", "饲料投喂", "养殖管理", "病害防控", "尾水排放"]
THEME_PATTERNS = {
    "尾水排放": r"尾水|排放|污染物|污水|面源污染",
    "病害防控": r"病害|疫病|病防|防治|防控|诊断|综合征|寄生虫|中毒|药敏|病情|消毒|疫区|药品|渔药|用药",
    "水质底质": r"水质|底质|底泥|水环境|水源|增氧|藻毒素|微囊藻",
    "苗种繁育": (
        r"苗种|鱼苗|虾苗|蟹苗|贝苗|苗场|繁育|繁殖|育苗|亲鱼|亲虾|亲贝|"
        r"种质|良种|孵化|育种|选育|幼体|淡化|标粗"
    ),
    "饲料投喂": r"饲料|饵料|投喂|饲喂",
    "养殖管理": (
        r"养殖|池塘|工厂化|循环水|稻渔|稻鱼|稻虾|稻蟹|稻鳖|稻蛙|网箱|"
        r"流水槽|渔场|生产管理|混养|套养|单养|设施|增养殖"
    ),
}
THEME_ATTR_RE = {theme: re.compile(THEME_PATTERNS[theme]) for theme in THEME_PATTERNS}

AQUATIC_RE = re.compile(
    r"水产|渔业|渔|鱼|虾|蟹|贝|藻|水生|稻渔|池塘|网箱|对虾|鲍|海参|珍珠|"
    r"龟|鳖|蛙|螺|蛏|蛤|牡蛎|扇贝|海带|紫菜|裙带菜|鱼粉|鱼油"
)

# Titles that match an aquatic character but are not aquaculture production.
NOISE_RE = re.compile(
    r"烹饪|菜谱|名菜|菜典|菜系|菜肴|宴|美食|小吃|面点|糕点|贝母|醉鱼草|"
    r"陶瓷|贝瓷|建材|猕猴桃|柠檬|地理标志|观赏|垂钓|休闲|旅游|文化|景观|"
    r"花园|乡村|民宿|餐饮|预制菜|烤鱼|鱼丸|鱼片|鱼干|鱼豆腐|鱼胶|鱼鳔|"
    r"鱼皮|鱼骨|鱼头|鱼粉|鱼油|蛋白肽|加工|制品|罐头|干制|腌制|熏制|"
    r"冷冻|保鲜|包装|标签|冷链|物流|交易|批发市场|品牌|出口|"
    r"饮用水|蓝藻水华|湖泛|气象|遥感|毒性分析|实验室|保护区|"
    r"犬|蔬菜|水稻|杂草|青贮|牧草|秸秆|捕捞|渔船|渔具|增殖放流|资源调查|"
    r"水产品|标准体系|饲料添加剂|水源水|畜禽|碳足迹|碳汇|金鱼"
)

# Reviewed false positives that survive the regex gate (title -> why not).
MANUAL_EXCLUDE: dict[str, str] = {
    "DB37/T 4855—2025": "海洋污染物毒性分析模式鱼种培育，非养殖生产",
    "DB32/T 4927-2024": "湖泊蓝藻水华气象评估，非水产养殖",
    "DB32/T 4816—2024": "湖库蓝藻水华预测预警，非水产养殖",
    "DB36/T 2220-2026": "饮用水水源蓝藻应急，非水产养殖",
    "DB43/T 434-2009": "病害实验室无害化处理，非养殖病害防控",
    "DB37/T 2297-2013": "贝类养殖区污染物筛选，偏环境监测",
    "DB42/T 2384-2025": "犬巴贝斯虫病，非水生动物",
    "DB50/T 1985-2026": "鱼菜共生蔬菜病虫害，非水生动物病害",
    "DB43/T 3040-2024": "稻虾田杂草防控，非水生动物病害",
    "DB4210/T 38-2020": "虾稻田水稻病虫害，非水生动物病害",
    "DB42/T 1574-2020": "虾稻共作水稻病虫害，非水生动物病害",
    "DB21/T 4311—2025": "活河蟹出口质量控制，非投喂技术",
    "DB34/T 3912-2021": "蓝藻应急原位处理，非养殖尾水",
    "DB31/T 1178-2019": "水源水微囊藻毒素测定，非养殖水体",
    "DB11/T 2262-2024": "观赏金鱼种质保护，非养殖生产",
    "DB44/T 2729—2025": "养殖海藻碳足迹核算，非养殖管理技术",
    "DB35/T 2238-2024": "养殖海带碳汇评估，非养殖管理技术",
    "DB31/T 1581-2025": "养殖蟹二噁英污染防控，偏食品污染物，非病害",
    "DB50/T 1644-2024": "畜禽养殖污水净化，非水产养殖",
    "DB37/T 4805—2024": "种质资源调查规范，非繁育技术",
}

# GB/T 2260 two-digit province codes (DB number prefix).
PROVINCES = {
    "11": "北京市",
    "12": "天津市",
    "13": "河北省",
    "14": "山西省",
    "15": "内蒙古自治区",
    "21": "辽宁省",
    "22": "吉林省",
    "23": "黑龙江省",
    "31": "上海市",
    "32": "江苏省",
    "33": "浙江省",
    "34": "安徽省",
    "35": "福建省",
    "36": "江西省",
    "37": "山东省",
    "41": "河南省",
    "42": "湖北省",
    "43": "湖南省",
    "44": "广东省",
    "45": "广西壮族自治区",
    "46": "海南省",
    "50": "重庆市",
    "51": "四川省",
    "52": "贵州省",
    "53": "云南省",
    "54": "西藏自治区",
    "61": "陕西省",
    "62": "甘肃省",
    "63": "青海省",
    "64": "宁夏回族自治区",
    "65": "新疆维吾尔自治区",
}

# Coarse 物种 categories requested for coverage.  Synonyms are folded in so a
# 波纹巴非蛤 counts as 贝 and a 虹鳟 counts as 鱼.
SPECIES_PATTERNS = [
    ("鳖", r"鳖|甲鱼"),
    ("鳅", r"鳅"),
    ("鳝", r"鳝"),
    ("虾", r"虾"),
    ("蟹", r"蟹"),
    ("贝", r"贝|蛤|蛏|螺|牡蛎|扇贝|鲍|蚶|蚌|蚬"),
    ("藻", r"藻|海带|紫菜|裙带菜|江蓠|浒苔"),
    ("鱼", r"鱼|鳟|鲑|鲈|鲷|鲆|鲽|鳗|鲟|鲤|鲫|鲢|鳙|鳊|鲮|鲇|鮰|鲴|鳜|鳢|鲳|鲹|鲅|鲱|鳕|鲀|鮡"),
]

QUOTAS = {
    "水质底质": 12,
    "苗种繁育": 18,
    "饲料投喂": 5,
    "养殖管理": 20,
    "病害防控": 13,
    "尾水排放": 12,
}
TARGET_TOTAL = 80


def normalise_number(value: str) -> str:
    """DB numbers appear with spaces and em/en dashes; compare one form."""
    return re.sub(r"[\s—–－]", "-", (value or "").strip()).upper()


def province_of(number: str) -> tuple[str | None, str | None]:
    match = re.match(r"DB\s*(\d{2})", number or "")
    if not match:
        return None, None
    code = match.group(1)
    return code, PROVINCES.get(code)


def species_categories(title: str) -> list[str]:
    # "虾夷扇贝" is a scallop: its leading "虾" must not tag the item as shrimp.
    cleaned = (title or "").replace("虾夷", "")
    hits = [name for name, pattern in SPECIES_PATTERNS if re.search(pattern, cleaned)]
    return hits or ["通用"]


def classify(title: str) -> str | None:
    for theme in ("尾水排放", "病害防控", "水质底质", "苗种繁育", "饲料投喂", "养殖管理"):
        if THEME_ATTR_RE[theme].search(title or ""):
            return theme
    return None


def load_existing_numbers() -> set[str]:
    numbers: set[str] = set()
    for path in INBOX.glob("*/meta.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        number = (meta.get("standard") or {}).get("number")
        if number:
            numbers.add(normalise_number(number))
    return numbers


def build_selection(catalog_path: Path, quotas: dict[str, int]) -> dict:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    records = catalog["platforms"]["std-db"]["records"]
    existing = load_existing_numbers()

    buckets: dict[str, list[dict]] = defaultdict(list)
    dropped: dict[str, int] = defaultdict(int)
    for record in records:
        title = record.get("name") or ""
        number = record.get("number") or ""
        if normalise_number(number) in existing:
            dropped["already_downloaded"] += 1
            continue
        if not AQUATIC_RE.search(title):
            dropped["not_aquatic_token"] += 1
            continue
        if NOISE_RE.search(title):
            dropped["noise_regex"] += 1
            continue
        if number in MANUAL_EXCLUDE:
            dropped["manual_exclude"] += 1
            continue
        theme = classify(title)
        if not theme:
            dropped["no_theme"] += 1
            continue
        code, province = province_of(number)
        item = {
            "number": number,
            "title": title,
            "status": record.get("status"),
            "issued": record.get("issued"),
            "effective": record.get("effective"),
            "replaces": record.get("replaces"),
            "detail_url": record.get("detail_url"),
            "platform": "dbba",
            "platform_label": "地方标准",
            "source_id": "std-db",
            "theme": theme,
            "province_code": code,
            "province": province,
            "species_categories": species_categories(title),
        }
        buckets[theme].append(item)

    selected: list[dict] = []
    for theme in THEME_ORDER:
        pool = buckets[theme]
        # Newest first inside every province, then round-robin across provinces
        # so one prolific province cannot fill the whole quota.
        pool.sort(key=lambda i: (i["effective"] or "", i["issued"] or "", i["number"]), reverse=True)
        by_province: dict[str, list[dict]] = defaultdict(list)
        for item in pool:
            by_province[item["province"] or "未知"].append(item)
        ordered_provinces = sorted(
            by_province,
            key=lambda p: (by_province[p][0]["effective"] or "", len(by_province[p])),
            reverse=True,
        )
        chosen: list[dict] = []
        quota = quotas.get(theme, 0)
        while len(chosen) < quota and any(by_province[p] for p in ordered_provinces):
            for province in ordered_provinces:
                if len(chosen) >= quota:
                    break
                if by_province[province]:
                    chosen.append(by_province[province].pop(0))
        for item in chosen:
            item["selection_rank"] = len(selected) + 1
            selected.append(item)

    # Spill unused quota to the themes with the deepest pools.
    if len(selected) < TARGET_TOTAL:
        chosen_numbers = {normalise_number(i["number"]) for i in selected}
        spill = [i for i in buckets["养殖管理"] + buckets["苗种繁育"] if normalise_number(i["number"]) not in chosen_numbers]
        spill.sort(key=lambda i: (i["effective"] or "", i["issued"] or ""), reverse=True)
        for item in spill:
            if len(selected) >= TARGET_TOTAL:
                break
            item["selection_rank"] = len(selected) + 1
            selected.append(item)

    coverage: dict[str, dict] = {}
    for theme in THEME_ORDER:
        rows = [i for i in selected if i["theme"] == theme]
        coverage[theme] = {
            "selected": len(rows),
            "candidates_available": len(buckets[theme]),
            "provinces": len({i["province"] for i in rows if i["province"]}),
        }
    provinces = sorted({i["province"] for i in selected if i["province"]})
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "catalog_generated_at": catalog.get("generated_at"),
        "catalog_today": catalog.get("today"),
        "rules": {
            "platform": "std-db (dbba.sacinfo.org.cn)",
            "themes": THEME_ORDER,
            "quotas": quotas,
            "target_total": TARGET_TOTAL,
            "noise_patterns": NOISE_RE.pattern,
            "manual_exclusions": MANUAL_EXCLUDE,
            "method": "aquatic+theme title match, drop non-aquaculture titles, "
            "newest first, round-robin across DB province prefixes",
        },
        "dropped": dict(dropped),
        "coverage": coverage,
        "province_count": len(provinces),
        "provinces": provinces,
        "selected": selected,
    }


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _download_url(detail_url: str) -> tuple[str, str]:
    pk = (detail_url or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{PLATFORMS['std-db']}/portal/download/{pk}", pk


def _meta_for(item: dict, body: bytes, response, pages: int, chars: int) -> dict:
    number = item["number"]
    title = item["title"]
    category = item["species_categories"]
    try:
        from app.species import species_in_text

        canonical = species_in_text(f"{title} {number}")
    except Exception:  # pragma: no cover - species table is optional here
        canonical = []
    return {
        "url": item["download_url"],
        "final_url": str(response.url),
        "title": f"{number} {title}".strip(),
        "format": "pdf",
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        # Both platforms only carry a site-wide "版权所有 侵权必究" footer; no
        # standard-text licence is stated anywhere on the page.
        "license": None,
        "license_note": "平台未声明标准文本使用许可（详情页仅有站点版权声明）",
        "license_class": "unclear",
        "publisher": None,
        "authority": "official_standard",
        "fetched_at": datetime.now(UTC).isoformat(),
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "detail_url": item["detail_url"],
        "doc_type": "standard",
        "language": "zh",
        "topics": ["水产标准", item["theme"]],
        "theme": item["theme"],
        "publish_date": item["issued"],
        "effective_date": item["effective"],
        "region": item["province"],
        "province_code": item["province_code"],
        "region_source": "DB 标准号前缀（GB/T 2260）",
        # 物种: coarse category requested for coverage, plus canonical names so
        # retrieval's species filter still works.
        "species_category": category,
        "species_label": "、".join(category),
        "species": canonical or ["通用"],
        "pages": pages,
        "text_chars": chars,
        "standard": {
            "number": number,
            "title": title,
            "status": item["status"],
            "issued": item["issued"],
            "effective": item["effective"],
            "replaces": item["replaces"],
            "platform": "dbba",
            "platform_label": "地方标准",
            "province": item["province"],
            "province_code": item["province_code"],
        },
    }


async def download(selection: dict, report_path: Path, rate: float) -> dict:
    from app.db import init_db

    await init_db()
    existing_urls, existing_details = await _existing_urls()
    throttle = Throttle(rate)
    import httpx

    result: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": "std-db",
        "target": len(selection["selected"]),
        "attempted": 0,
        "downloaded": 0,
        "failed": 0,
        "skipped_existing": 0,
        "bytes": 0,
        "text_layer": {"usable": 0, "needs_ocr": 0, "empty": 0},
        "failures": [],
        "items": [],
    }
    async with httpx.AsyncClient(
        timeout=120, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        for item in selection["selected"]:
            url, _pk = _download_url(item["detail_url"])
            item["download_url"] = url
            if url in existing_urls or item["detail_url"] in existing_details:
                result["skipped_existing"] += 1
                continue
            result["attempted"] += 1
            label = f"{item['number']} {item['title']}"
            try:
                response = await _get(client, throttle, url, item["detail_url"])
                if response.status_code != 200:
                    raise RuntimeError(f"http_{response.status_code}")
                body = response.content
                if not body.startswith(b"%PDF"):
                    raise RuntimeError(f"not_pdf:{response.headers.get('content-type')}")
                if len(body) < 1024:
                    raise RuntimeError(f"too_small:{len(body)}")
                pages, chars = await asyncio.to_thread(_pdf_stats, body)
            except Exception as exc:  # one bad standard must not abort the batch
                result["failed"] += 1
                result["failures"].append(
                    {"number": item["number"], "title": item["title"], "error": str(exc)[:200]}
                )
                print(f"  FAIL {label}: {exc}")
                continue

            sha = hashlib.sha256(body).hexdigest()
            slug = sha[:16]
            target = INBOX / slug
            target.mkdir(parents=True, exist_ok=True)
            (target / "original.pdf").write_bytes(body)
            meta = _meta_for(item, body, response, pages, chars)
            (target / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            data_item_id = await _insert_item(meta, item)

            existing_urls.add(url)
            existing_details.add(item["detail_url"])
            needs_ocr = chars <= 200
            result["downloaded"] += 1
            result["bytes"] += len(body)
            result["text_layer"]["needs_ocr" if needs_ocr else "usable"] += 1
            if chars == 0:
                result["text_layer"]["empty"] += 1
            result["items"].append(
                {
                    "number": item["number"],
                    "title": item["title"],
                    "theme": item["theme"],
                    "province": item["province"],
                    "species": meta["species_label"],
                    "effective": item["effective"],
                    "url": url,
                    "detail_url": item["detail_url"],
                    "sha256": sha,
                    "slug": slug,
                    "bytes": len(body),
                    "pages": pages,
                    "text_chars": chars,
                    "text_layer": "needs_ocr" if needs_ocr else "usable",
                    "data_item_id": data_item_id,
                }
            )
            print(
                f"  OK   {label} pages={pages} chars={chars}"
                f"{' NEEDS_OCR' if needs_ocr else ''}"
            )

    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog", default=str(ROOT / "data" / "reports" / "standards_catalog.json")
    )
    parser.add_argument("--selection", default=str(DEFAULT_SELECTION))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--rate", type=float, default=2.1)
    parser.add_argument("--limit", type=int, default=None, help="download only the first N")
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    selection = build_selection(Path(args.catalog), QUOTAS)
    if args.limit:
        selection["selected"] = selection["selected"][: args.limit]
    Path(args.selection).write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"selected {len(selection['selected'])} standards")
    for theme in THEME_ORDER:
        row = selection["coverage"][theme]
        print(f"  {theme:<6} {row['selected']:>3} / {row['candidates_available']} candidates, {row['provinces']} provinces")
    print(f"provinces: {selection['province_count']} -> {', '.join(selection['provinces'])}")
    print(f"dropped: {selection['dropped']}")
    print(f"-> {args.selection}")

    if args.download:
        result = asyncio.run(download(selection, Path(args.report), args.rate))
        print(
            f"downloaded={result['downloaded']} failed={result['failed']} "
            f"skipped={result['skipped_existing']} "
            f"text={result['text_layer']['usable']} ocr={result['text_layer']['needs_ocr']}"
        )
        print(f"-> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())