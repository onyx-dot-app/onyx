from __future__ import annotations

from onyx.search_gateway.models import SearchMode
from onyx.search_gateway.query_planner import build_effective_queries


def test_lite_mode_keeps_original_queries_only() -> None:
    assert build_effective_queries(
        ["  swc-project / swc  ", "SWC architecture"],
        mode=SearchMode.LITE,
    ) == ["swc-project / swc", "SWC architecture"]


def test_medium_mode_expands_technical_query_without_deep_breadth() -> None:
    queries = build_effective_queries(
        ["swc-project / swc"],
        mode=SearchMode.MEDIUM,
    )

    assert queries[0] == "swc-project / swc"
    assert 3 <= len(queries) <= 5
    query_text = "\n".join(queries).lower()
    assert "official documentation" in query_text
    assert "github" in query_text
    assert "changelog" in query_text or "release notes" in query_text
    assert "comparison" in query_text or "benchmark" in query_text


def test_deep_mode_expands_technical_project_query_into_source_angles() -> None:
    queries = build_effective_queries(
        ["swc-project / swc"],
        mode=SearchMode.DEEP,
    )

    assert queries[0] == "swc-project / swc"
    assert 5 <= len(queries) <= 8
    query_text = "\n".join(queries).lower()
    assert "official documentation" in query_text
    assert "github" in query_text
    assert "changelog" in query_text or "release notes" in query_text
    assert "issues" in query_text or "discussion" in query_text
    assert "comparison" in query_text or "benchmark" in query_text
    assert "limitations" in query_text


def test_deep_mode_dedupes_and_caps_expanded_queries() -> None:
    queries = build_effective_queries(
        ["swc", "swc", "swc docs"],
        mode=SearchMode.DEEP,
        max_queries=6,
    )

    assert len(queries) == 6
    assert len(queries) == len(set(queries))
    assert queries[0] == "swc"
