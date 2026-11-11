"""LinearConnector.reindex across batches, with the gateway mocked."""

import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.linear.source_operations import LinearAuthError
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure

_BATCH_SIZE = 2


def _node(issue_id: str) -> dict[str, Any]:
    return {
        "id": issue_id,
        "identifier": "ENG-1",
        "title": "Issue",
        "url": f"https://linear.app/onyx/issue/ENG-1/{issue_id}",
        "description": "body",
        "comments": {"nodes": []},
        "team": {"name": "Engineering"},
        "createdAt": "2026-01-01T00:00:00.000Z",
        "updatedAt": "2026-01-02T00:00:00.000Z",
    }


def _connector(
    fail_on: set[str], error: Exception
) -> tuple[LinearConnector, MagicMock]:
    """A connector whose issue query raises `error` for any batch that
    holds an id in `fail_on`."""

    def iterate_issues(
        *,
        issue_filter: dict[str, Any],
        page_size: int,  # noqa: ARG001
    ) -> Iterator[list[dict[str, Any]]]:
        ids: list[str] = issue_filter["id"]["in"]
        if fail_on & set(ids):
            raise error
        yield [_node(issue_id) for issue_id in ids]

    ops = MagicMock()
    ops.iterate_issues.side_effect = iterate_issues
    connector = LinearConnector(batch_size=_BATCH_SIZE)
    connector._ops = ops
    return connector, ops


def _failures(ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=issue_id),
            failure_message="synthetic",
        )
        for issue_id in ids
    ]


def test_a_failed_batch_fails_only_its_own_ids() -> None:
    ids = [str(uuid.uuid4()) for _ in range(5)]
    connector, ops = _connector({ids[2]}, RuntimeError("Linear is down"))

    results = list(connector.reindex(_failures(ids)))

    assert ops.iterate_issues.call_count == 3
    assert sorted(r.id for r in results if isinstance(r, Document)) == sorted(
        [ids[0], ids[1], ids[4]]
    )
    assert sorted(
        r.failed_document.document_id
        for r in results
        if isinstance(r, ConnectorFailure) and r.failed_document
    ) == sorted([ids[2], ids[3]])


def test_a_refused_credential_stops_the_run() -> None:
    ids = [str(uuid.uuid4()) for _ in range(5)]
    connector, _ = _connector(
        {ids[2]}, LinearAuthError("refused", status_code=200, body=None)
    )

    with pytest.raises(LinearAuthError):
        list(connector.reindex(_failures(ids)))
