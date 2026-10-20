"""The check graph: a ``checks.json`` loads and validates, and the served
graph follows the registered checks."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import graph
from onyx.connectors.capability_checks.graph import (
    CheckGraphError,
    load_check_graph,
)
from onyx.connectors.capability_checks.registry import get_check_graph


@pytest.fixture(autouse=True)
def _fresh_graphs() -> Iterator[None]:
    load_check_graph.cache_clear()
    get_check_graph.cache_clear()
    yield
    load_check_graph.cache_clear()
    get_check_graph.cache_clear()


def _write_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nodes_json: str
) -> None:
    path = tmp_path / "checks.json"
    path.write_text(f'{{"source": "jira", "nodes": {nodes_json}}}')
    monkeypatch.setattr(graph, "_graph_paths", lambda _source: [path])


def test_graph_edges_keep_each_dependents_order() -> None:
    edges = get_check_graph(DocumentSource.JIRA).edges

    assert [
        edge.prerequisite for edge in edges if edge.dependent == "jira_issue_read"
    ] == ["jira_projects_visible", "jira_configured_project", "jira_jql_query"]


def test_a_duplicate_id_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_graph(
        monkeypatch,
        tmp_path,
        '[{"id": "a", "display_name": "A"}, {"id": "a", "display_name": "A"}]',
    )

    with pytest.raises(CheckGraphError, match="duplicate"):
        load_check_graph(DocumentSource.JIRA)


def test_a_dependency_on_an_unknown_check_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_graph(
        monkeypatch,
        tmp_path,
        '[{"id": "a", "display_name": "A", "depends_on": ["missing"]}]',
    )

    with pytest.raises(CheckGraphError, match="unknown"):
        load_check_graph(DocumentSource.JIRA)


def test_a_cycle_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_graph(
        monkeypatch,
        tmp_path,
        '[{"id": "a", "display_name": "A", "depends_on": ["b"]},'
        ' {"id": "b", "display_name": "B", "depends_on": ["a"]}]',
    )

    with pytest.raises(CheckGraphError, match="cycle"):
        load_check_graph(DocumentSource.JIRA)


def test_an_unknown_field_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_graph(
        monkeypatch, tmp_path, '[{"id": "a", "display_name": "A", "requird": false}]'
    )

    with pytest.raises(ValueError):
        load_check_graph(DocumentSource.JIRA)


def test_a_source_without_a_file_has_no_nodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        graph, "_graph_paths", lambda _source: [tmp_path / "checks.json"]
    )

    assert load_check_graph(DocumentSource.JIRA) == ()


def test_a_source_without_named_checks_serves_its_fallback_node() -> None:
    nodes = get_check_graph(DocumentSource.BITBUCKET).nodes

    indexing = [node for node in nodes if node.capability.value == "indexing"]
    assert [node.id for node in indexing] == ["bitbucket_connector_settings"]
    assert indexing[0].is_fallback
