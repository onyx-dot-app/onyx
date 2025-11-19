from datetime import datetime

import pytest
import pytz
import timeago  # type: ignore

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.onyxbot.slack.blocks import _build_documents_blocks


def _make_saved_doc(updated_at: datetime | None) -> SavedSearchDoc:
    return SavedSearchDoc(
        db_doc_id=1,
        document_id="doc-1",
        chunk_ind=0,
        semantic_identifier="Example Doc",
        link="https://example.com",
        blurb="Some blurb",
        source_type=DocumentSource.FILE,
        boost=0,
        hidden=False,
        metadata={},
        score=0.0,
        match_highlights=[],
        updated_at=updated_at,
        primary_owners=["user@example.com"],
        secondary_owners=None,
        is_relevant=None,
        relevance_explanation=None,
        is_internet=False,
    )


def test_build_documents_blocks_formats_naive_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    naive_timestamp: datetime = datetime(2024, 1, 1, 12, 0, 0)
    captured: dict[str, datetime] = {}

    # Save the original timeago.format so we can call it inside the fake
    original_timeago_format = timeago.format

    def fake_timeago_format(doc_dt: datetime, now: datetime) -> str:
        captured["doc"] = doc_dt
        result = original_timeago_format(doc_dt, now)
        captured["result"] = result
        return result

    monkeypatch.setattr(
        "onyx.onyxbot.slack.blocks.timeago.format",
        fake_timeago_format,
    )

    blocks = _build_documents_blocks(
        documents=[_make_saved_doc(updated_at=naive_timestamp)],
        message_id=42,
    )

    assert len(blocks) >= 2
    section_block = blocks[1].to_dict()
    assert "result" in captured
    expected_text = (
        "<https://example.com|Example Doc>\n_Updated " f"{captured['result']}_\n>"
    )
    assert section_block["text"]["text"] == expected_text

    assert "doc" in captured
    formatted_timestamp: datetime = captured["doc"]
    expected_timestamp: datetime = naive_timestamp.replace(tzinfo=pytz.utc)
    assert formatted_timestamp == expected_timestamp
