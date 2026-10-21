"""Every source's ``checks.json``: the OSS file holds exactly the source's
named indexing checks, the EE file exactly its named permission-sync checks,
and each check carries its node's metadata."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ee.onyx.connectors import capability_checks as ee_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import graph, registry
from onyx.connectors.capability_checks.graph import check_node, load_check_graph
from onyx.connectors.capability_checks.models import CapabilityCheck

_BACKEND_ROOT = Path(graph.__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fresh_graphs() -> Iterator[None]:
    load_check_graph.cache_clear()
    yield
    load_check_graph.cache_clear()


def _indexing_checks(source: DocumentSource) -> list[CapabilityCheck]:
    return list(registry._INDEXING_CHECKS_BY_SOURCE.get(source, []))


def _perm_sync_checks(source: DocumentSource) -> list[CapabilityCheck]:
    return list(
        ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE.get(source, [])
    ) + list(ee_capability_checks._EXTERNAL_GROUP_SYNC_CHECKS_BY_SOURCE.get(source, []))


def _file_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        node.id
        for node in graph.CheckGraphFile.model_validate_json(path.read_text()).nodes
    }


_SOURCES_WITH_NAMED_CHECKS = sorted(
    set(registry._INDEXING_CHECKS_BY_SOURCE)
    | set(ee_capability_checks._DOC_PERMISSION_SYNC_CHECKS_BY_SOURCE)
    | set(ee_capability_checks._EXTERNAL_GROUP_SYNC_CHECKS_BY_SOURCE),
    key=lambda source: source.value,
)


@pytest.mark.parametrize(
    "source", _SOURCES_WITH_NAMED_CHECKS, ids=lambda source: source.value
)
def test_checks_json_holds_exactly_the_registered_checks(
    source: DocumentSource,
) -> None:
    oss_path = _BACKEND_ROOT / "onyx" / "connectors" / source.value / "checks.json"
    ee_path = (
        _BACKEND_ROOT
        / "ee"
        / "onyx"
        / "external_permissions"
        / source.value
        / "checks.json"
    )
    indexing_ids = {check.check_id for check in _indexing_checks(source)}
    perm_sync_ids = {check.check_id for check in _perm_sync_checks(source)}

    # A node lives in the file of its first registration: a check that
    # indexing registers is in the OSS file, even when EE also registers it
    # for a permission-sync capability. The EE file holds the EE-only checks.
    assert _file_ids(oss_path) == indexing_ids
    assert _file_ids(ee_path) == perm_sync_ids - indexing_ids


@pytest.mark.parametrize(
    "source", _SOURCES_WITH_NAMED_CHECKS, ids=lambda source: source.value
)
def test_each_node_lists_every_capability_it_is_registered_for(
    source: DocumentSource,
) -> None:
    registered: dict[str, list[str]] = {}
    for check in _indexing_checks(source) + _perm_sync_checks(source):
        registered.setdefault(check.check_id, []).append(check.capability.value)

    for check_id, capabilities in registered.items():
        node = check_node(source, check_id)
        assert [capability.value for capability in node.capabilities] == capabilities


@pytest.mark.parametrize(
    "source", _SOURCES_WITH_NAMED_CHECKS, ids=lambda source: source.value
)
def test_each_check_carries_its_nodes_metadata(source: DocumentSource) -> None:
    for check in _indexing_checks(source) + _perm_sync_checks(source):
        node = check_node(source, check.check_id)
        assert check.display_name == node.display_name
        assert check.capability in node.capabilities
        assert check.depends_on == node.depends_on
        assert check.row_id == (node.row_id or node.id)
        assert check.requires_fields == frozenset(node.requires_fields)
