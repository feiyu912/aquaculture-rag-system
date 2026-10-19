from __future__ import annotations

import uuid

from app.graph.service import EntityData, GraphData, RelationData, expand_entities, mention_entities


def _data() -> tuple[GraphData, dict[str, uuid.UUID]]:
    ids = {name: uuid.uuid4() for name in ("溶解氧", "水质", "增氧", "浮头")}
    entities = {
        ids["溶解氧"]: EntityData(ids["溶解氧"], "溶解氧", "WATER_PARAMETER", ["溶氧", "DO"]),
        ids["水质"]: EntityData(ids["水质"], "水质", "WATER_CONDITION", []),
        ids["增氧"]: EntityData(ids["增氧"], "增氧", "MANAGEMENT_MEASURE", ["增氧机"]),
        ids["浮头"]: EntityData(ids["浮头"], "浮头", "SYMPTOM", []),
    }
    relations = [
        RelationData(ids["溶解氧"], ids["水质"], "INDICATOR_OF"),
        RelationData(ids["增氧"], ids["溶解氧"], "MANAGEMENT_FOR"),
        RelationData(ids["浮头"], ids["溶解氧"], "ASSOCIATED_WITH"),
    ]
    return GraphData(entities=entities, relations=relations), ids


def test_alias_linking_prefers_longest_term():
    graph, ids = _data()
    mentions = mention_entities("溶解氧偏低时开启增氧机", graph)
    assert ids["溶解氧"] in mentions
    assert ids["增氧"] in mentions


def test_one_hop_expansion_is_verified_and_traced():
    graph, ids = _data()
    expansion = expand_entities("溶解氧偏低怎么办？", graph)
    assert ids["溶解氧"] in expansion.seed_entity_ids
    assert ids["水质"] in expansion.expanded_entity_ids
    assert expansion.expanded_terms == ["水质"]
    assert expansion.relation_trace[0]["relation_type"] == "INDICATOR_OF"


def test_no_graph_match_returns_empty_expansion():
    graph, _ = _data()
    expansion = expand_entities("今天上海天气怎么样？", graph)
    assert expansion.seed_entity_ids == []
    assert expansion.expanded_entity_ids == []
