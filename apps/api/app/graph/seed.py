"""Small, human-reviewed seed graph.

This is intentionally tiny: it only contains generic aquaculture water-quality
concepts and well-known aliases.  Document-extracted relations must carry
provenance and review status and are not seeded here.
"""

from __future__ import annotations

SEED_ENTITIES: list[dict] = [
    {"name": "溶解氧", "entity_type": "WATER_PARAMETER", "aliases": ["溶氧", "DO"]},
    {"name": "氨氮", "entity_type": "WATER_PARAMETER", "aliases": ["氨态氮"]},
    {"name": "亚硝酸盐", "entity_type": "WATER_PARAMETER", "aliases": ["NO2-N"]},
    {"name": "酸碱度", "entity_type": "WATER_PARAMETER", "aliases": ["pH", "PH"]},
    {"name": "水温", "entity_type": "WATER_PARAMETER", "aliases": []},
    {"name": "盐度", "entity_type": "WATER_PARAMETER", "aliases": []},
    {"name": "水质", "entity_type": "WATER_CONDITION", "aliases": ["水体环境"]},
    {"name": "增氧", "entity_type": "MANAGEMENT_MEASURE", "aliases": ["增氧机", "机械增氧"]},
    {"name": "浮头", "entity_type": "SYMPTOM", "aliases": ["缺氧浮头"]},
    {"name": "中华绒螯蟹", "entity_type": "SPECIES", "aliases": ["河蟹", "绒螯蟹"]},
    {"name": "凡纳滨对虾", "entity_type": "SPECIES", "aliases": ["南美白对虾", "白对虾"]},
]

SEED_RELATIONS: list[tuple[str, str, str]] = [
    ("溶解氧", "水质", "INDICATOR_OF"),
    ("氨氮", "水质", "INDICATOR_OF"),
    ("亚硝酸盐", "水质", "INDICATOR_OF"),
    ("酸碱度", "水质", "INDICATOR_OF"),
    ("水温", "水质", "INDICATOR_OF"),
    ("盐度", "水质", "INDICATOR_OF"),
    ("增氧", "溶解氧", "MANAGEMENT_FOR"),
    ("浮头", "溶解氧", "ASSOCIATED_WITH"),
]
