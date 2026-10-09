from datetime import datetime

import pytest
import pytz
import timeago

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.onyxbot.slack.blocks import _build_sources_blocks


def _make_saved_doc(
    updated_at: datetime | None,
    semantic_identifier: str = "Example Doc",
    link: str | None = "https://example.com",
    primary_owner: str = "user@example.com",
) -> SavedSearchDoc:
    return SavedSearchDoc(
        db_doc_id=1,
        document_id="doc-1",
        chunk_ind=0,
        semantic_identifier=semantic_identifier,
        link=link,
        blurb="Some blurb",
        source_type=DocumentSource.FILE,
        boost=0,
        hidden=False,
        metadata={},
        score=0.0,
        match_highlights=[],
        updated_at=updated_at,
        primary_owners=[primary_owner],
        secondary_owners=None,
        is_relevant=None,
        relevance_explanation=None,
        is_internet=False,
    )


def test_build_sources_blocks_formats_naive_timestamp(
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

    blocks = _build_sources_blocks(
        cited_documents=[(1, _make_saved_doc(updated_at=naive_timestamp))],
    )

    assert len(blocks) == 2
    context_block = blocks[1].to_dict()
    assert "result" in captured
    expected_text = (
        f"*<https://example.com|[1] Example Doc>*\n"
        f"By user@example.com | {captured['result']}"
    )
    assert context_block["elements"][1]["text"] == expected_text
    assert context_block["elements"][1]["verbatim"] is True

    assert "doc" in captured
    formatted_timestamp: datetime = captured["doc"]
    expected_timestamp: datetime = naive_timestamp.replace(tzinfo=pytz.utc)
    assert formatted_timestamp == expected_timestamp


def test_build_sources_blocks_keeps_link_syntax_flat() -> None:
    document = _make_saved_doc(
        updated_at=None,
        semantic_identifier="Run [portal](https://n.e) <https://a.e>",
        link="https://example.com/a|b>c",
    )

    blocks = _build_sources_blocks(cited_documents=[(1, document)])

    text = blocks[1].to_dict()["elements"][1]["text"]
    assert "*<https://example.com/a%7Cb&gt;c|[1] Run portal https://a.e>*" in text
    assert text.count("<") == 1
    assert text.count(">") == 1


def test_build_sources_blocks_handles_missing_document_link() -> None:
    document = _make_saved_doc(updated_at=None, link=None)

    blocks = _build_sources_blocks(cited_documents=[(1, document)])

    markdown = blocks[1].to_dict()["elements"][1]
    assert markdown["text"] == "Example Doc"
    assert markdown["verbatim"] is True


def test_build_sources_blocks_defangs_owner_mentions() -> None:
    document = _make_saved_doc(
        updated_at=None,
        primary_owner="<@U123> <!channel> @here",
    )

    blocks = _build_sources_blocks(cited_documents=[(1, document)])

    text = blocks[1].to_dict()["elements"][1]["text"]
    assert "By &lt;@U123&gt; &lt;!channel&gt; @here" in text
