from datetime import datetime, timezone

import pytest

from onyx.db.postgres_tool import POSTGRES_TOOL_MAX_LIMIT
from onyx.db.postgres_tool_models import DocumentCursor, GroupCount
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.postgres.postgres_tool import (
    _decode_cursor,
    _encode_cursor,
    _format_group_counts,
)


def test_group_counts_are_cut_at_the_cap() -> None:
    groups = [GroupCount(group=f"owner-{i}", count=1) for i in range(101)]
    text = _format_group_counts(groups, "documents", "owner")
    header, *lines = text.split("\n")
    assert header.startswith(
        f"Matching documents by owner, top {POSTGRES_TOOL_MAX_LIMIT}"
    )
    assert "there are more" in header
    assert len(lines) == POSTGRES_TOOL_MAX_LIMIT
    assert "owner-100: 1" not in lines


@pytest.mark.parametrize(
    "cursor",
    [
        DocumentCursor(
            updated_at=datetime(2026, 2, 3, 4, 5, 6, 789012, tzinfo=timezone.utc),
            document_id="https://example.com/a?b=c",
        ),
        DocumentCursor(updated_at=None, document_id="doc-1"),
    ],
)
def test_cursor_round_trip(cursor: DocumentCursor) -> None:
    token = _encode_cursor(cursor, "query-a")
    assert _decode_cursor(token, "query-a") == cursor


def test_cursor_is_bound_to_its_query() -> None:
    token = _encode_cursor(DocumentCursor(updated_at=None, document_id="d"), "query-a")
    with pytest.raises(ToolCallException) as error:
        _decode_cursor(token, "query-b")
    assert "different filters" in error.value.llm_facing_message
    for broken in ("", "%%%", token[:-4], "WzFd"):
        with pytest.raises(ToolCallException):
            _decode_cursor(broken, "query-a")
