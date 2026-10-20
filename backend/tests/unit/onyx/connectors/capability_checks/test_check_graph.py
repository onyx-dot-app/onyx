"""The check graph: each source's ``checks.json`` loads, validates, and
matches the checks the code registers."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import graph
from onyx.connectors.capability_checks.graph import (
    CheckGraphError,
    check_node,
    load_check_graph,
)
from onyx.connectors.capability_checks.registry import get_check_graph
from onyx.connectors.jira.capability_checks import (
    build_jira_doc_permission_sync_checks,
    build_jira_group_sync_checks,
    build_jira_indexing_checks,
)

_BACKEND_ROOT = Path(graph.__file__).resolve().parents[3]


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


def test_every_graph_file_loads_and_validates() -> None:
    files = sorted(_BACKEND_ROOT.glob("onyx/connectors/*/checks.json")) + sorted(
        _BACKEND_ROOT.glob("ee/onyx/external_permissions/*/checks.json")
    )
    assert files, "no check graph files found"
    for path in files:
        source = DocumentSource(path.parent.name)
        assert load_check_graph(source), f"{path} has no nodes"


def test_jira_graph_holds_exactly_the_registered_checks() -> None:
    built = (
        build_jira_indexing_checks()
        + build_jira_doc_permission_sync_checks()
        + build_jira_group_sync_checks()
    )

    assert {node.id for node in load_check_graph(DocumentSource.JIRA)} == {
        check.check_id for check in built
    }


def test_a_check_reads_its_metadata_from_its_node() -> None:
    node = check_node(DocumentSource.JIRA, "jira_scoped_token_auth")
    check = next(
        check
        for check in build_jira_indexing_checks()
        if check.check_id == "jira_scoped_token_auth"
    )

    assert check.display_name == node.display_name
    assert check.row_id == node.row_id == "jira_auth"
    assert check.requires_fields == frozenset(node.requires_fields)
    assert check.depends_on == node.depends_on


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
