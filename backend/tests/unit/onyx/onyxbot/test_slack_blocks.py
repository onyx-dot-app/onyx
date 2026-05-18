from datetime import datetime

import pytest
import pytz
import timeago
from slack_sdk.models.blocks import HeaderBlock
from slack_sdk.models.blocks import SectionBlock

from onyx.chat.models import ChatBasicResponse
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.onyxbot.slack.blocks import _build_documents_blocks
from onyx.onyxbot.slack.blocks import _build_sources_blocks
from onyx.onyxbot.slack.blocks import _priority_ordered_documents_blocks
from onyx.onyxbot.slack.blocks import build_slack_response_blocks
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.models import ThreadMessage
from onyx.server.query_and_chat.streaming_models import CitationInfo


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
        f"<https://example.com|Example Doc>\n_Updated {captured['result']}_\n>"
    )
    assert section_block["text"]["text"] == expected_text

    assert "doc" in captured
    formatted_timestamp: datetime = captured["doc"]
    expected_timestamp: datetime = naive_timestamp.replace(tzinfo=pytz.utc)
    assert formatted_timestamp == expected_timestamp


def _make_doc(doc_id: str, semantic_identifier: str | None = None) -> SearchDoc:
    return SavedSearchDoc(
        db_doc_id=hash(doc_id) & 0xFFFFFF,
        document_id=doc_id,
        chunk_ind=0,
        semantic_identifier=semantic_identifier or doc_id,
        link=f"https://example.com/{doc_id}",
        blurb="blurb",
        source_type=DocumentSource.FILE,
        boost=0,
        hidden=False,
        metadata={},
        score=0.0,
        match_highlights=[],
        updated_at=None,
        primary_owners=[],
        secondary_owners=None,
        is_relevant=None,
        relevance_explanation=None,
        is_internet=False,
    )


def _make_answer(
    top_document_ids: list[str],
    cited_document_ids: list[str] | None = None,
) -> ChatBasicResponse:
    cited = cited_document_ids or []
    citation_info = [
        CitationInfo(citation_number=i + 1, document_id=doc_id)
        for i, doc_id in enumerate(cited)
    ]
    return ChatBasicResponse(
        answer="some answer",
        answer_citationless="some answer",
        top_documents=[_make_doc(doc_id) for doc_id in top_document_ids],
        error_msg=None,
        message_id=1,
        citation_info=citation_info,
    )


def _make_slack_message_info() -> SlackMessageInfo:
    return SlackMessageInfo(
        thread_messages=[ThreadMessage(message="hello?")],
        channel_to_respond="C123",
        msg_to_respond="1.0",
        thread_to_respond=None,
        sender_id="U1",
        email=None,
        bypass_filters=False,
        is_slash_command=False,
        is_bot_dm=False,
    )


def _has_header(blocks: list, text: str) -> bool:
    return any(
        isinstance(b, HeaderBlock) and b.text.text == text  # type: ignore[union-attr]
        for b in blocks
    )


def _has_sources_section(blocks: list) -> bool:
    return any(
        isinstance(b, SectionBlock) and b.text is not None and "*Sources:*" in b.text.text  # type: ignore[union-attr]
        for b in blocks
    )


def test_build_slack_response_blocks_cited_and_retrieved_disjoint() -> None:
    """When cited and retrieved sets are disjoint, both sections render,
    and the retrieved section excludes any cited doc."""
    answer = _make_answer(
        top_document_ids=[f"doc-{i}" for i in range(8)],
        cited_document_ids=["doc-0", "doc-1"],
    )
    blocks = build_slack_response_blocks(
        answer=answer,
        message_info=_make_slack_message_info(),
        channel_conf=None,
        feedback_reminder_id=None,
        skip_restated_question=True,
    )

    assert _has_sources_section(blocks)
    assert _has_header(blocks, "Reference Documents")


def test_build_slack_response_blocks_all_retrieved_cited() -> None:
    """When every retrieved doc is cited, the retrieved section is omitted."""
    ids = ["doc-a", "doc-b", "doc-c"]
    answer = _make_answer(top_document_ids=ids, cited_document_ids=ids)
    blocks = build_slack_response_blocks(
        answer=answer,
        message_info=_make_slack_message_info(),
        channel_conf=None,
        feedback_reminder_id=None,
        skip_restated_question=True,
    )

    assert _has_sources_section(blocks)
    assert not _has_header(blocks, "Reference Documents")


def test_build_slack_response_blocks_no_citations_retrieved_present() -> None:
    """When there are no citations, retrieved docs render as 'Reference Documents'."""
    answer = _make_answer(
        top_document_ids=[f"doc-{i}" for i in range(4)],
        cited_document_ids=[],
    )
    blocks = build_slack_response_blocks(
        answer=answer,
        message_info=_make_slack_message_info(),
        channel_conf=None,
        feedback_reminder_id=None,
        skip_restated_question=True,
    )

    assert not _has_sources_section(blocks)
    assert _has_header(blocks, "Reference Documents")


def test_build_slack_response_blocks_no_citations_no_retrieved() -> None:
    """When both citations and retrieved are empty, neither section renders."""
    answer = _make_answer(top_document_ids=[], cited_document_ids=[])
    blocks = build_slack_response_blocks(
        answer=answer,
        message_info=_make_slack_message_info(),
        channel_conf=None,
        feedback_reminder_id=None,
        skip_restated_question=True,
    )

    assert not _has_sources_section(blocks)
    assert not _has_header(blocks, "Reference Documents")


@pytest.mark.parametrize("cap", [1, 3, 5])
def test_build_sources_blocks_respects_cap(cap: int) -> None:
    """The cited-docs cap must actually fire. Regression guard for the
    previously-missing `included_docs += 1` increment."""
    cited_docs = [(i + 1, _make_doc(f"doc-{i}")) for i in range(10)]
    blocks = _build_sources_blocks(
        cited_documents=cited_docs,
        num_docs_to_display=cap,
    )

    # blocks[0] is the "*Sources:*" SectionBlock header; every subsequent block
    # is one ContextBlock per included doc.
    context_blocks = [b for b in blocks if b.__class__.__name__ == "ContextBlock"]
    assert len(context_blocks) == cap


@pytest.mark.parametrize("cap", [1, 3, 5, 10])
def test_build_documents_blocks_respects_explicit_cap(cap: int) -> None:
    docs = [_make_doc(f"doc-{i}") for i in range(15)]
    blocks = _build_documents_blocks(
        documents=docs,
        message_id=None,
        num_docs_to_display=cap,
    )
    section_block_count = sum(
        1 for b in blocks if b.__class__.__name__ == "SectionBlock"
    )
    assert section_block_count == cap


def test_priority_ordered_documents_blocks_excludes_given_ids() -> None:
    answer = _make_answer(
        top_document_ids=["doc-a", "doc-b", "doc-c"],
        cited_document_ids=[],
    )
    blocks = _priority_ordered_documents_blocks(
        answer,
        exclude_doc_ids={"doc-a", "doc-b"},
    )

    # Only doc-c should make it through.
    section_blocks = [b for b in blocks if isinstance(b, SectionBlock)]
    assert len(section_blocks) == 1
    section_text = section_blocks[0].text
    assert section_text is not None
    assert "doc-c" in section_text.text


def test_priority_ordered_documents_blocks_all_excluded_returns_empty() -> None:
    answer = _make_answer(
        top_document_ids=["doc-a", "doc-b"],
        cited_document_ids=[],
    )
    blocks = _priority_ordered_documents_blocks(
        answer,
        exclude_doc_ids={"doc-a", "doc-b"},
    )
    assert blocks == []
