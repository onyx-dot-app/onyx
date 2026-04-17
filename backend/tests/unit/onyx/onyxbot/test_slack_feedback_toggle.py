from slack_sdk.models.blocks import ActionsBlock

from onyx.chat.models import ChatBasicResponse
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.db.models import ChannelConfig
from onyx.onyxbot.slack.blocks import build_slack_response_blocks
from onyx.onyxbot.slack.constants import DISLIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import LIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.models import ThreadMessage


def _make_doc(doc_id: str) -> SearchDoc:
    return SavedSearchDoc(
        db_doc_id=hash(doc_id) & 0xFFFFFF,
        document_id=doc_id,
        chunk_ind=0,
        semantic_identifier=doc_id,
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


def _make_answer() -> ChatBasicResponse:
    return ChatBasicResponse(
        answer="some answer",
        answer_citationless="some answer",
        top_documents=[_make_doc("doc-1")],
        error_msg=None,
        message_id=42,
        citation_info=[],
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


def _has_qa_feedback_buttons(blocks: list) -> bool:
    for block in blocks:
        if not isinstance(block, ActionsBlock):
            continue
        action_ids = {
            element.action_id
            for element in block.elements
            if hasattr(element, "action_id")
        }
        if LIKE_BLOCK_ACTION_ID in action_ids and DISLIKE_BLOCK_ACTION_ID in action_ids:
            return True
    return False


def test_feedback_buttons_rendered_when_skip_ai_feedback_false() -> None:
    blocks = build_slack_response_blocks(
        answer=_make_answer(),
        message_info=_make_slack_message_info(),
        channel_conf=None,
        feedback_reminder_id=None,
        skip_ai_feedback=False,
        skip_restated_question=True,
    )
    assert _has_qa_feedback_buttons(blocks)


def test_feedback_buttons_suppressed_when_skip_ai_feedback_true() -> None:
    blocks = build_slack_response_blocks(
        answer=_make_answer(),
        message_info=_make_slack_message_info(),
        channel_conf=None,
        feedback_reminder_id=None,
        skip_ai_feedback=True,
        skip_restated_question=True,
    )
    assert not _has_qa_feedback_buttons(blocks)


def test_channel_config_disable_ai_feedback_field_roundtrips() -> None:
    """The `disable_ai_feedback` field is a valid ChannelConfig key and
    can be read via .get() with a default like the handler does."""
    config: ChannelConfig = {
        "channel_name": "test",
        "disable_ai_feedback": True,
    }
    assert config.get("disable_ai_feedback", False) is True

    config_unset: ChannelConfig = {"channel_name": "test"}
    assert config_unset.get("disable_ai_feedback", False) is False
