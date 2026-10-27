"""_get_live_hierarchy_node_ids: the hierarchy nodes a prune keeps linked."""

from unittest.mock import MagicMock

import pytest

from onyx.background.celery.celery_utils import SlimConnectorExtractionResult
from onyx.background.celery.tasks.pruning import tasks as pruning_tasks
from onyx.configs.constants import DocumentSource

_SOURCE = DocumentSource.CONFLUENCE
_YIELDED_NODE_IDS = {1, 2}


def _extraction_result(
    listed_from: float | None,
) -> SlimConnectorExtractionResult:
    return SlimConnectorExtractionResult(
        raw_id_to_parent={
            "doc-a": "folder-1",
            "doc-b": "folder-1",
            "doc-c": "folder-2",
            "doc-d": None,
        },
        hierarchy_nodes=[],
        id_to_created_at={},
        listed_from=listed_from,
    )


def test_full_listing_keeps_only_the_yielded_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    walk = MagicMock()
    monkeypatch.setattr(pruning_tasks, "get_hierarchy_node_ids_with_ancestors", walk)

    live = pruning_tasks._get_live_hierarchy_node_ids(
        db_session=MagicMock(),
        source=_SOURCE,
        extraction_result=_extraction_result(listed_from=None),
        yielded_node_ids=_YIELDED_NODE_IDS,
    )

    assert live == _YIELDED_NODE_IDS
    walk.assert_not_called()


@pytest.mark.parametrize("documents_are_nodes", [True, False])
def test_dated_listing_adds_the_ancestors_of_kept_documents(
    monkeypatch: pytest.MonkeyPatch, documents_are_nodes: bool
) -> None:
    walk = MagicMock(return_value={1, 2, 3, 4})
    monkeypatch.setattr(pruning_tasks, "get_hierarchy_node_ids_with_ancestors", walk)
    monkeypatch.setattr(
        pruning_tasks,
        "source_has_document_hierarchy_nodes",
        MagicMock(return_value=documents_are_nodes),
    )
    db_session = MagicMock()

    live = pruning_tasks._get_live_hierarchy_node_ids(
        db_session=db_session,
        source=_SOURCE,
        extraction_result=_extraction_result(listed_from=1_700_000_000.0),
        yielded_node_ids=_YIELDED_NODE_IDS,
    )

    assert live == {1, 2, 3, 4}
    # Each parent once; a document with no parent adds no seed. Documents
    # seed only for a source where a node can be a document.
    walk.assert_called_once_with(
        db_session=db_session,
        source=_SOURCE,
        raw_node_ids={"folder-1", "folder-2"},
        node_ids=_YIELDED_NODE_IDS,
        document_ids=(
            {"doc-a", "doc-b", "doc-c", "doc-d"} if documents_are_nodes else set()
        ),
    )
