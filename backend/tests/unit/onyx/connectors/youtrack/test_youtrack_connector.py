"""YouTrack issue mapping: the search query the connector sends, the document
it builds (public comments and fields only), the per-project checkpoint, and
the slim walk that pruning trusts."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import Document, HierarchyNode
from onyx.connectors.youtrack.connector import (
    YouTrackCheckpoint,
    YouTrackConnector,
    issue_query,
    scoped_query,
)
from onyx.connectors.youtrack.models import (
    YouTrackComment,
    YouTrackIssue,
    YouTrackProject,
    YouTrackSlimIssue,
)

_BASE_URL = "https://example.youtrack.cloud"
_PROJECT: dict[str, Any] = {"id": "0-1", "shortName": "ABC", "name": "Alpha"}
_LIMITED: dict[str, Any] = {"$type": "LimitedVisibility", "permittedGroups": []}
_UNLIMITED: dict[str, Any] = {"$type": "UnlimitedVisibility"}


def _issue(**overrides: Any) -> YouTrackIssue:
    raw: dict[str, Any] = {
        "id": "2-15",
        "idReadable": "ABC-15",
        "summary": "Login fails",
        "description": "Steps to reproduce",
        "created": 1_700_000_000_000,
        "updated": 1_700_000_500_000,
        "project": _PROJECT,
        "reporter": {"id": "1-1", "fullName": "Ada", "email": "ada@example.com"},
        "comments": [],
        "commentsCount": 0,
    }
    raw.update(overrides)
    return YouTrackIssue.model_validate(raw)


def _connector(**kwargs: Any) -> tuple[YouTrackConnector, MagicMock]:
    connector = YouTrackConnector(base_url=f"{_BASE_URL}/", **kwargs)
    ops = MagicMock()
    ops.list_projects.return_value = [YouTrackProject.model_validate(_PROJECT)]
    connector._ops = ops
    return connector, ops


def _run(
    connector: YouTrackConnector,
    checkpoint: YouTrackCheckpoint,
    start: float = 0,
    end: float = 2_000_000_000,
) -> tuple[list[Document | HierarchyNode], YouTrackCheckpoint]:
    items: list[Document | HierarchyNode] = []
    wrapper = CheckpointOutputWrapper[YouTrackCheckpoint]()
    for document, node, failure, next_checkpoint in wrapper(
        connector.load_from_checkpoint(start, end, checkpoint)
    ):
        assert failure is None
        if document is not None:
            items.append(document)
        if node is not None:
            items.append(node)
        if next_checkpoint is not None:
            checkpoint = next_checkpoint
    return items, checkpoint


def _documents(connector: YouTrackConnector) -> list[Document]:
    items, _ = _run(connector, connector.build_dummy_checkpoint())
    return [item for item in items if isinstance(item, Document)]


def test_issue_query_widens_the_window_by_a_day_and_sorts_by_created() -> None:
    start = datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc)
    end = datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)
    assert (
        issue_query(["ABC", "DEF"], start, end)
        == "project: {ABC}, {DEF} updated: 2026-10-13 .. 2026-10-16 sort by: created asc"
    )
    assert issue_query([]) == "sort by: created asc"


def test_document_keeps_public_comments_and_public_fields_only() -> None:
    connector, ops = _connector()
    comments: list[dict[str, Any]] = [
        {"id": "4-1", "text": "public", "created": 1, "visibility": _UNLIMITED},
        {"id": "4-2", "text": "restricted", "created": 2, "visibility": _LIMITED},
        {"id": "4-3", "text": "deleted", "created": 3, "deleted": True},
    ]
    fields: list[dict[str, Any]] = [
        {"$type": "StateIssueCustomField", "name": "State", "value": {"name": "Open"}},
        {
            "$type": "MultiUserIssueCustomField",
            "name": "Assignees",
            "value": [{"fullName": "Ada"}, {"fullName": "Bob"}],
        },
        {"$type": "DateIssueCustomField", "name": "Due", "value": 1_760_486_400_000},
        {
            "$type": "SimpleIssueCustomField",
            "name": "Secret",
            "value": "hidden",
            "projectCustomField": {"isPublic": False},
        },
    ]
    ops.iterate_issues.return_value = iter(
        [[_issue(comments=comments, commentsCount=3, customFields=fields)]]
    )

    (doc,) = _documents(connector)

    assert doc.id == f"{_BASE_URL}/api/issues/2-15"
    assert doc.semantic_identifier == "[ABC-15] Login fails"
    assert [s.text for s in doc.sections] == ["Steps to reproduce", "public"]
    assert doc.metadata == {
        "project": "Alpha",
        "State": "Open",
        "Assignees": ["Ada", "Bob"],
        "Due": "2025-10-15",
    }
    assert doc.parent_hierarchy_raw_node_id == f"{_BASE_URL}/api/admin/projects/0-1"
    ops.list_issue_comments.assert_not_called()


def test_truncated_comment_list_is_refetched() -> None:
    connector, ops = _connector()
    ops.iterate_issues.return_value = iter([[_issue(commentsCount=2)]])
    ops.list_issue_comments.return_value = [
        YouTrackComment.model_validate({"id": "4-9", "text": "late", "created": 9})
    ]

    (doc,) = _documents(connector)

    assert [s.text for s in doc.sections][1:] == ["late"]
    ops.list_issue_comments.assert_called_once_with(issue_id="2-15")


def test_poll_drops_issues_outside_the_exact_window() -> None:
    connector, ops = _connector(projects=["ABC"])
    inside = _issue(id="2-1", idReadable="ABC-1", updated=1_700_000_500_000)
    before = _issue(id="2-2", idReadable="ABC-2", updated=1_699_000_000_000)
    ops.iterate_issues.return_value = iter([[inside, before]])

    items, _ = _run(
        connector, connector.build_dummy_checkpoint(), 1_700_000_000, 1_700_001_000
    )

    assert isinstance(items[0], HierarchyNode)
    assert [item.id for item in items[1:] if isinstance(item, Document)] == [
        f"{_BASE_URL}/api/issues/2-1"
    ]


def test_each_run_indexes_one_project_and_the_checkpoint_resumes_at_the_next() -> None:
    connector, ops = _connector()
    other: dict[str, Any] = {"id": "0-2", "shortName": "DEF", "name": "Delta"}
    ops.list_projects.return_value = [
        YouTrackProject.model_validate(_PROJECT),
        YouTrackProject.model_validate(other),
    ]
    ops.iterate_issues.side_effect = lambda query: iter(
        [[_issue(project=other if "{DEF}" in query else _PROJECT)]]
    )

    first, checkpoint = _run(connector, connector.build_dummy_checkpoint())
    assert [item.display_name for item in first if isinstance(item, HierarchyNode)] == [
        "Alpha"
    ]
    assert checkpoint.has_more

    resumed = connector.validate_checkpoint_json(checkpoint.model_dump_json())
    second, checkpoint = _run(connector, resumed)
    assert [
        item.display_name for item in second if isinstance(item, HierarchyNode)
    ] == ["Delta"]
    assert not checkpoint.has_more
    assert [c.kwargs["query"] for c in ops.iterate_issues.call_args_list] == [
        "project: {ABC} updated: * .. 2033-05-19 sort by: created asc",
        "project: {DEF} updated: * .. 2033-05-19 sort by: created asc",
    ]


def test_slim_walk_raises_when_stopped() -> None:
    connector, ops = _connector()
    page: list[YouTrackSlimIssue] = [
        YouTrackSlimIssue.model_validate(
            {"id": "2-1", "created": 1, "project": _PROJECT}
        )
    ]
    ops.iterate_slim_issues.return_value = iter([page])
    callback = MagicMock()
    callback.should_stop.return_value = True

    walk: Iterator[Any] = connector.retrieve_all_slim_docs(callback=callback)
    with pytest.raises(RuntimeError):
        next(walk)


def test_validation_names_every_missing_project() -> None:
    connector, ops = _connector(projects=["ABC", "XYZ", "QQ"])
    ops.list_projects.return_value = [YouTrackProject.model_validate(_PROJECT)]

    with pytest.raises(ConnectorValidationError, match="QQ, XYZ"):
        connector.validate_connector_settings()


def test_archived_projects_leave_the_query_and_an_all_archived_scope_reads_nothing() -> (
    None
):
    connector, ops = _connector(projects=["ABC", "OLD"])
    ops.list_projects.return_value = [
        YouTrackProject.model_validate(_PROJECT),
        YouTrackProject.model_validate(
            {"id": "0-9", "shortName": "OLD", "name": "Old", "archived": True}
        ),
    ]
    assert (
        scoped_query(ops, connector.projects) == "project: {ABC} sort by: created asc"
    )

    ops.list_projects.return_value = ops.list_projects.return_value[1:]
    assert list(connector.retrieve_all_slim_docs()) == []
    ops.iterate_slim_issues.assert_not_called()
    items, checkpoint = _run(connector, connector.build_dummy_checkpoint())
    assert items == []
    assert not checkpoint.has_more
    ops.iterate_issues.assert_not_called()


def test_a_queued_project_archived_before_its_turn_is_skipped() -> None:
    connector, ops = _connector()
    other: dict[str, Any] = {"id": "0-2", "shortName": "DEF", "name": "Delta"}
    ops.iterate_issues.return_value = iter([[_issue()]])

    checkpoint = YouTrackCheckpoint(has_more=True, project_ids=["0-2", "0-1"])
    ops.list_projects.return_value = [
        YouTrackProject.model_validate({**other, "archived": True}),
        YouTrackProject.model_validate(_PROJECT),
    ]
    items, checkpoint = _run(connector, checkpoint)

    assert [item.display_name for item in items if isinstance(item, HierarchyNode)] == [
        "Alpha"
    ]
    assert [c.kwargs["query"] for c in ops.iterate_issues.call_args_list] == [
        "project: {ABC} updated: * .. 2033-05-19 sort by: created asc"
    ]
    assert not checkpoint.has_more
