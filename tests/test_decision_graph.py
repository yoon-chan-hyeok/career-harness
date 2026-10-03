import pytest
from career.decision_graph import EdgeProposal, add_relations, approve_graph, graph_view, search_graphs
from career.domain import save_entity
from career.truth import add_evidence, invalidate_source, register_source


def graph(db):
    text = "제약을 확인했다. 실패를 관찰했다. 가설을 줄였다. 다른 방법을 선택했다."
    source, _ = register_source(db, "a", "graph-fixture", text, "RAW_RESULT")
    evidence = add_evidence(db, "a", source.id, "실패를 통한 전환", text, status="VERIFIED")
    episode = save_entity(
        db,
        "a",
        "DecisionEpisode",
        {
            "source_id": source.id,
            "evidence_id": evidence.id,
            "situation": "작업",
            "constraint": "제약을 확인했다.",
            "observation": "실패를 관찰했다.",
            "options": ["기존 방법", "다른 방법"],
            "decision": "다른 방법을 선택했다.",
            "action": "가설을 줄였다.",
            "outcome": "한계 확인",
            "lesson": "범위 대조",
            "hypothesis": "개선 가능성",
            "reduced_claim": "가설을 줄였다.",
            "rejected_hypothesis": "기존 방법 포기",
            "reframe": "한계로 재해석",
            "outcome_kind": "NEGATIVE",
        },
        explicit_confirmation=True,
    )
    graphs = search_graphs(db, "a")
    assert graphs and graphs[0]["data"]["episode_id"] == episode.id
    return source, evidence, graphs[0]


def test_graph_preserves_provenance_negative_experience_and_user_boundary(db):
    source, _, item = graph(db)
    assert all(node["source_id"] == source.id for node in item["data"]["nodes"])
    assert all(
        edge["kind"] == "EPISODE_NEXT" and edge["basis"] == "STRUCTURAL_EPISODE_ORDER"
        for edge in item["data"]["edges"]
    )
    assert search_graphs(db, "a", intent="FAILURE_REFRAMING")[0]["id"] == item["id"]
    assert search_graphs(db, "a", intent="NARROWED_HYPOTHESIS")
    assert search_graphs(db, "b") == []
    with pytest.raises(LookupError):
        graph_view(db, "b", item["id"])
    invalidate_source(db, "a", source.id)
    assert search_graphs(db, "a") == []
    assert graph_view(db, "a", item["id"])["data"]["nodes"] == []


def test_causal_edges_require_exact_quote_and_human_confirmation(db):
    _, evidence, item = graph(db)
    nodes = item["data"]["nodes"]
    bad = EdgeProposal(
        from_node_id=nodes[0]["id"], to_node_id=nodes[-1]["id"], kind="LED_TO", quote="invented cause"
    )
    with pytest.raises(ValueError, match="인용"):
        add_relations(db, "a", item["id"], [bad])
    result = add_relations(db, "a", item["id"], [bad.model_copy(update={"quote": evidence.body})])
    assert result["data"]["status"] == "PENDING"
    assert search_graphs(db, "a") == []
    with pytest.raises(ValueError, match="확인"):
        approve_graph(db, "a", result["id"], False)
    approved = approve_graph(db, "a", result["id"], True)
    assert approved["data"]["edges"][-1]["basis"] == "HUMAN_CONFIRMED_RELATION"
    assert search_graphs(db, "a")[0]["id"] == approved["id"]
