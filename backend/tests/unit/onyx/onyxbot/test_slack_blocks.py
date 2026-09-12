import json
from datetime import datetime

import pytest
import pytz
import timeago
from slack_sdk.models.blocks import Block

from onyx.chat.models import ChatBasicResponse
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.onyxbot.slack.blocks import _build_sources_blocks, build_slack_response_blocks
from onyx.onyxbot.slack.constants import (
    DISLIKE_BLOCK_ACTION_ID,
    FOLLOWUP_BUTTON_ACTION_ID,
    LIKE_BLOCK_ACTION_ID,
    SHOW_EVERYONE_ACTION_ID,
)
from onyx.onyxbot.slack.models import SlackMessageInfo, ThreadMessage


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


def _make_answer() -> ChatBasicResponse:
    return ChatBasicResponse(
        answer="An answer",
        answer_citationless="An answer",
        top_documents=[],
        error_msg=None,
        message_id=42,
        citation_info=[],
    )


def _make_message_info() -> SlackMessageInfo:
    return SlackMessageInfo(
        thread_messages=[ThreadMessage(message="A question?")],
        channel_to_respond="C123",
        msg_to_respond="123.456",
        thread_to_respond="123.456",
        sender_id="U123",
        email="user@example.com",
        bypass_filters=False,
        is_slash_command=False,
        is_bot_dm=False,
    )


def _get_action_ids(blocks: list[Block]) -> set[str]:
    return {
        element["action_id"]
        for block in blocks
        for element in block.to_dict().get("elements", [])
        if "action_id" in element
    }


def test_build_slack_response_blocks_removes_feedback_buttons_when_configured() -> None:
    blocks = build_slack_response_blocks(
        answer=_make_answer(),
        message_info=_make_message_info(),
        channel_conf={
            "channel_name": "general",
            "follow_up_tags": [],
            "remove_feedback_buttons": True,
        },
        feedback_reminder_id=None,
    )

    action_ids = _get_action_ids(blocks)

    assert LIKE_BLOCK_ACTION_ID not in action_ids
    assert DISLIKE_BLOCK_ACTION_ID not in action_ids
    assert FOLLOWUP_BUTTON_ACTION_ID in action_ids


def test_build_slack_response_blocks_keeps_feedback_buttons_by_default() -> None:
    blocks = build_slack_response_blocks(
        answer=_make_answer(),
        message_info=_make_message_info(),
        channel_conf={"channel_name": "general"},
        feedback_reminder_id=None,
    )

    action_ids = _get_action_ids(blocks)

    assert LIKE_BLOCK_ACTION_ID in action_ids
    assert DISLIKE_BLOCK_ACTION_ID in action_ids


def test_ephemeral_publication_preserves_remove_feedback_buttons_setting() -> None:
    blocks = build_slack_response_blocks(
        answer=_make_answer(),
        message_info=_make_message_info(),
        channel_conf={
            "channel_name": "general",
            "is_ephemeral": True,
            "remove_feedback_buttons": True,
        },
        feedback_reminder_id=None,
        offer_ephemeral_publication=True,
        skip_ai_feedback=True,
    )

    publish_button = next(
        element
        for block in blocks
        for element in block.to_dict().get("elements", [])
        if element.get("action_id") == SHOW_EVERYONE_ACTION_ID
    )
    action_value = json.loads(publish_button["value"])

    assert action_value["channel_conf"]["remove_feedback_buttons"] is True


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
