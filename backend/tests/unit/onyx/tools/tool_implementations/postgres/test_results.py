from datetime import datetime, timezone

import pytest

from onyx.db.postgres_tool import POSTGRES_TOOL_MAX_LIMIT
from onyx.db.postgres_tool_models import (
    DocumentCursor,
    DocumentOrder,
    DocumentScope,
    GroupCount,
)
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.postgres.models import PostgresQueryArgs
from onyx.tools.tool_implementations.postgres.postgres_tool import (
    _decode_cursor,
    _document_query_key,
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
    ("cursor", "order"),
    [
        (
            DocumentCursor(
                sort_value=datetime(2026, 2, 3, 4, 5, 6, 789012, tzinfo=timezone.utc),
                document_id="https://example.com/a?b=c",
            ),
            DocumentOrder.UPDATED_DESC,
        ),
        (
            DocumentCursor(sort_value=None, document_id="doc-1"),
            DocumentOrder.CREATED_ASC,
        ),
        # A title that looks like a date stays a title.
        (
            DocumentCursor(sort_value="2026-01-01 notes", document_id="d"),
            DocumentOrder.TITLE_ASC,
        ),
        (
            DocumentCursor(sort_value="2026-01-01", document_id="d"),
            DocumentOrder.TITLE_DESC,
        ),
    ],
)
def test_cursor_round_trip(cursor: DocumentCursor, order: DocumentOrder) -> None:
    token = _encode_cursor(cursor, "query-a")
    assert _decode_cursor(token, "query-a", order) == cursor


def test_cursor_is_bound_to_its_query() -> None:
    token = _encode_cursor(DocumentCursor(sort_value=None, document_id="d"), "query-a")
    with pytest.raises(ToolCallException) as error:
        _decode_cursor(token, "query-b", DocumentOrder.UPDATED_DESC)
    assert "different filters" in error.value.llm_facing_message
    for broken in ("", "%%%", token[:-4], "WzFd"):
        with pytest.raises(ToolCallException):
            _decode_cursor(broken, "query-a", DocumentOrder.UPDATED_DESC)


def test_metadata_cursor_keys_did_not_change() -> None:
    # The key that the tool gave this query before documents took
    # content_contains, so cursors issued then still work.
    args = PostgresQueryArgs(table="document", title_contains=["pricing"])
    assert _document_query_key(args, DocumentScope()) == "2c1d6e5f5e15aa27"
    with_content = args.model_copy(update={"content_contains": ["pricing"]})
    assert _document_query_key(with_content, DocumentScope()) != "2c1d6e5f5e15aa27"
