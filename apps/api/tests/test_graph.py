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
    expansion = expand_entities("溶解氧偏低怎么办？", graph, max_hops=1, bidirectional=False)
    assert ids["溶解氧"] in expansion.seed_entity_ids
    assert ids["水质"] in expansion.expanded_entity_ids
    assert expansion.expanded_terms == ["水质"]
    assert expansion.relation_trace[0]["relation_type"] == "INDICATOR_OF"
    assert expansion.relation_trace[0]["direction"] == "forward"
    assert expansion.relation_trace[0]["hop"] == 1


def test_two_hop_expansion_traces_full_path_and_stops_at_limit():
    nodes = {name: uuid.uuid4() for name in ("A", "B", "C")}
    entities = {node: EntityData(node, name, "TEST") for name, node in nodes.items()}
    relations = [
        RelationData(nodes["A"], nodes["B"], "NEXT"),
        RelationData(nodes["B"], nodes["C"], "NEXT"),
    ]
    graph = GraphData(entities=entities, relations=relations)

    two_hop = expand_entities("A", graph, max_hops=2, bidirectional=False)
    assert set(two_hop.expanded_terms) == {"B", "C"}
    assert [item["hop"] for item in two_hop.relation_trace] == [1, 2]
    assert two_hop.relation_trace[-1]["path"] == ["A", "B", "C"]
    assert len(two_hop.relation_trace[-1]["path_entity_ids"]) == 3

    one_hop = expand_entities("A", graph, max_hops=1, bidirectional=False)
    assert set(one_hop.expanded_terms) == {"B"}
    assert one_hop.max_hops == 1


def test_bidirectional_expansion_reaches_management_from_symptom():
    graph, ids = _data()
    expansion = expand_entities("浮头怎么办？", graph, max_hops=2, bidirectional=True)
    assert ids["增氧"] in expansion.expanded_entity_ids
    assert ids["水质"] in expansion.expanded_entity_ids
    reverse = [item for item in expansion.relation_trace if item["direction"] == "reverse"]
    assert reverse
    assert reverse[0]["relation_type"] == "MANAGEMENT_FOR"


def test_invalid_hop_limit_is_rejected():
    graph, _ = _data()
    try:
        expand_entities("溶解氧", graph, max_hops=0)
    except ValueError as exc:
        assert "max_hops" in str(exc)
    else:
        raise AssertionError("max_hops=0 must fail")


def test_no_graph_match_returns_empty_expansion():
    graph, _ = _data()
    expansion = expand_entities("今天上海天气怎么样？", graph)
    assert expansion.seed_entity_ids == []
    assert expansion.expanded_entity_ids == []


def test_seed_graph_connects_species_to_water_quality():
    from app.graph.seed import SEED_RELATIONS

    assert ("中华绒螯蟹", "水质", "SPECIES_HABITAT") in SEED_RELATIONS
    assert ("凡纳滨对虾", "水质", "SPECIES_HABITAT") in SEED_RELATIONS
