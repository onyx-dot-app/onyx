"""Tests for Slack channel reference resolution and tag filtering
in handle_regular_answer.py."""

from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from slack_sdk.errors import SlackApiError

from onyx.chat.models import ChatBasicResponse
from onyx.context.search.models import Tag
from onyx.onyxbot.slack.constants import SLACK_CHANNEL_REF_PATTERN
from onyx.onyxbot.slack.handlers.handle_regular_answer import handle_regular_answer
from onyx.onyxbot.slack.handlers.handle_regular_answer import resolve_channel_references
from onyx.onyxbot.slack.handlers.handle_regular_answer import (
    SLACK_PERSONA_ACCESS_DENIED_MESSAGE,
)
from onyx.onyxbot.slack.models import ChannelType
from onyx.onyxbot.slack.models import SlackContext
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.models import ThreadMessage

_HANDLE_REGULAR_ANSWER = "onyx.onyxbot.slack.handlers.handle_regular_answer"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client_with_channels(
    channel_map: dict[str, str],
) -> MagicMock:
    """Return a mock WebClient where conversations_info resolves IDs to names."""
    client = MagicMock()

    def _conversations_info(channel: str) -> MagicMock:
        if channel in channel_map:
            resp = MagicMock()
            resp.validate = MagicMock()
            resp.__getitem__ = lambda _self, key: {
                "channel": {
                    "name": channel_map[channel],
                    "is_im": False,
                    "is_mpim": False,
                }
            }[key]
            return resp
        raise SlackApiError("channel_not_found", response=MagicMock())

    client.conversations_info = _conversations_info
    return client


def _mock_logger() -> MagicMock:
    return MagicMock()


def _make_slack_message_info(
    channel_type: ChannelType,
    is_slash_command: bool = False,
    is_bot_dm: bool = False,
    sender_id: str | None = "U123",
) -> SlackMessageInfo:
    message_ts = None if is_slash_command else "111.222"
    return SlackMessageInfo(
        thread_messages=[ThreadMessage(message="answer this?", sender="User")],
        channel_to_respond="C123",
        msg_to_respond=message_ts,
        thread_to_respond=message_ts,
        sender_id=sender_id,
        email="user@test.com",
        bypass_filters=True,
        is_slash_command=is_slash_command,
        is_bot_dm=is_bot_dm,
        slack_context=SlackContext(
            channel_type=channel_type,
            channel_id="C123",
            user_id="U123",
            message_ts=message_ts,
        ),
    )


def _identity_decorator(
    *_args: object, **_kwargs: object
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    def _decorate(func: Callable[..., object]) -> Callable[..., object]:
        return func

    return _decorate


def _make_slack_channel_config(
    is_ephemeral: bool = False,
) -> MagicMock:
    persona = MagicMock()
    persona.id = 123
    persona.name = "Scoped Agent"
    persona.document_sets = []

    slack_channel_config = MagicMock()
    slack_channel_config.persona = persona
    slack_channel_config.persona_id = persona.id
    slack_channel_config.channel_config = {"is_ephemeral": is_ephemeral}
    return slack_channel_config


def _assert_access_denied_response(
    message_info: SlackMessageInfo,
    slack_channel_config: MagicMock,
    expected_receiver_ids: list[str] | None,
    expected_thread_ts: str | None,
    expected_send_as_ephemeral: bool,
    expect_reaction_removal: bool,
) -> None:
    user = MagicMock()
    client = MagicMock()
    db_session = MagicMock()
    logger = _mock_logger()

    with (
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email", return_value=user),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_persona_by_id",
            side_effect=ValueError("persona access denied"),
        ) as mock_get_persona_by_id,
        patch(f"{_HANDLE_REGULAR_ANSWER}.respond_in_thread_or_channel") as mock_respond,
        patch(f"{_HANDLE_REGULAR_ANSWER}.update_emote_react") as mock_update_react,
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.handle_stream_message_objects"
        ) as mock_handle_stream_message_objects,
    ):
        result = handle_regular_answer(
            message_info=message_info,
            slack_channel_config=slack_channel_config,
            receiver_ids=None,
            client=client,
            channel="C123",
            logger=logger,
            db_session=db_session,
            feedback_reminder_id=None,
            should_respond_with_error_msgs=False,
        )

    assert result is False
    mock_get_persona_by_id.assert_called_once_with(
        persona_id=slack_channel_config.persona_id,
        user=user,
        db_session=db_session,
        is_for_edit=False,
    )
    mock_respond.assert_called_once_with(
        client=client,
        channel="C123",
        receiver_ids=expected_receiver_ids,
        text=SLACK_PERSONA_ACCESS_DENIED_MESSAGE,
        thread_ts=expected_thread_ts,
        send_as_ephemeral=expected_send_as_ephemeral,
    )
    if expect_reaction_removal:
        assert mock_update_react.call_args.kwargs["remove"] is True
    else:
        mock_update_react.assert_not_called()
    mock_handle_stream_message_objects.assert_not_called()


# ---------------------------------------------------------------------------
# SLACK_CHANNEL_REF_PATTERN regex tests
# ---------------------------------------------------------------------------


class TestSlackChannelRefPattern:
    def test_matches_bare_channel_id(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("<#C097NBWMY8Y>")
        assert matches == [("C097NBWMY8Y", "")]

    def test_matches_channel_id_with_name(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("<#C097NBWMY8Y|eng-infra>")
        assert matches == [("C097NBWMY8Y", "eng-infra")]

    def test_matches_multiple_channels(self) -> None:
        msg = "compare <#C111AAA> and <#C222BBB|general>"
        matches = SLACK_CHANNEL_REF_PATTERN.findall(msg)
        assert len(matches) == 2
        assert ("C111AAA", "") in matches
        assert ("C222BBB", "general") in matches

    def test_no_match_on_plain_text(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("no channels here")
        assert matches == []

    def test_no_match_on_user_mention(self) -> None:
        matches = SLACK_CHANNEL_REF_PATTERN.findall("<@U12345>")
        assert matches == []


# ---------------------------------------------------------------------------
# resolve_channel_references tests
# ---------------------------------------------------------------------------


class TestResolveChannelReferences:
    def test_resolves_bare_channel_id_via_api(self) -> None:
        client = _mock_client_with_channels({"C097NBWMY8Y": "eng-infra"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="summary of <#C097NBWMY8Y> this week",
            client=client,
            logger=logger,
        )

        assert message == "summary of #eng-infra this week"
        assert len(tags) == 1
        assert tags[0] == Tag(tag_key="Channel", tag_value="eng-infra")

    def test_uses_name_from_pipe_format_without_api_call(self) -> None:
        client = MagicMock()
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="check <#C097NBWMY8Y|eng-infra> for updates",
            client=client,
            logger=logger,
        )

        assert message == "check #eng-infra for updates"
        assert tags == [Tag(tag_key="Channel", tag_value="eng-infra")]
        # Should NOT have called the API since name was in the markup
        client.conversations_info.assert_not_called()

    def test_multiple_channels(self) -> None:
        client = _mock_client_with_channels(
            {
                "C111AAA": "eng-infra",
                "C222BBB": "eng-general",
            }
        )
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="compare <#C111AAA> and <#C222BBB>",
            client=client,
            logger=logger,
        )

        assert "#eng-infra" in message
        assert "#eng-general" in message
        assert "<#" not in message
        assert len(tags) == 2
        tag_values = {t.tag_value for t in tags}
        assert tag_values == {"eng-infra", "eng-general"}

    def test_no_channel_references_returns_unchanged(self) -> None:
        client = MagicMock()
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="just a normal message with no channels",
            client=client,
            logger=logger,
        )

        assert message == "just a normal message with no channels"
        assert tags == []

    def test_api_failure_skips_channel_gracefully(self) -> None:
        # Client that fails for all channel lookups
        client = _mock_client_with_channels({})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="check <#CBADID123>",
            client=client,
            logger=logger,
        )

        # Message should remain unchanged for the failed channel
        assert "<#CBADID123>" in message
        assert tags == []
        logger.warning.assert_called_once()

    def test_partial_failure_resolves_what_it_can(self) -> None:
        # Only one of two channels resolves
        client = _mock_client_with_channels({"C111AAA": "eng-infra"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="compare <#C111AAA> and <#CBADID123>",
            client=client,
            logger=logger,
        )

        assert "#eng-infra" in message
        assert "<#CBADID123>" in message  # failed one stays raw
        assert len(tags) == 1
        assert tags[0].tag_value == "eng-infra"

    def test_duplicate_channel_produces_single_tag(self) -> None:
        client = _mock_client_with_channels({"C111AAA": "eng-infra"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="summarize <#C111AAA> and compare with <#C111AAA>",
            client=client,
            logger=logger,
        )

        assert message == "summarize #eng-infra and compare with #eng-infra"
        assert len(tags) == 1
        assert tags[0].tag_value == "eng-infra"

    def test_mixed_pipe_and_bare_formats(self) -> None:
        client = _mock_client_with_channels({"C222BBB": "random"})
        logger = _mock_logger()

        message, tags = resolve_channel_references(
            message="see <#C111AAA|eng-infra> and <#C222BBB>",
            client=client,
            logger=logger,
        )

        assert "#eng-infra" in message
        assert "#random" in message
        assert len(tags) == 2


@pytest.mark.parametrize(
    (
        "channel_type",
        "is_ephemeral",
        "is_slash_command",
        "is_bot_dm",
        "expected_receiver_ids",
        "expected_thread_ts",
        "expected_send_as_ephemeral",
        "expect_reaction_removal",
    ),
    [
        pytest.param(
            ChannelType.PUBLIC_CHANNEL,
            False,
            False,
            False,
            ["U123"],
            "111.222",
            True,
            True,
            id="public-channel",
        ),
        pytest.param(
            ChannelType.PRIVATE_CHANNEL,
            False,
            False,
            False,
            ["U123"],
            "111.222",
            True,
            True,
            id="private-channel",
        ),
        pytest.param(
            ChannelType.PRIVATE_CHANNEL,
            True,
            False,
            False,
            ["U123"],
            None,
            True,
            True,
            id="configured-ephemeral",
        ),
        pytest.param(
            ChannelType.PUBLIC_CHANNEL,
            False,
            True,
            False,
            ["U123"],
            None,
            True,
            False,
            id="slash-command",
        ),
        pytest.param(
            ChannelType.IM,
            False,
            False,
            True,
            None,
            "111.222",
            False,
            True,
            id="dm",
        ),
    ],
)
def test_persona_access_denied_response(
    channel_type: ChannelType,
    is_ephemeral: bool,
    is_slash_command: bool,
    is_bot_dm: bool,
    expected_receiver_ids: list[str] | None,
    expected_thread_ts: str | None,
    expected_send_as_ephemeral: bool,
    expect_reaction_removal: bool,
) -> None:
    _assert_access_denied_response(
        message_info=_make_slack_message_info(
            channel_type=channel_type,
            is_slash_command=is_slash_command,
            is_bot_dm=is_bot_dm,
        ),
        slack_channel_config=_make_slack_channel_config(is_ephemeral=is_ephemeral),
        expected_receiver_ids=expected_receiver_ids,
        expected_thread_ts=expected_thread_ts,
        expected_send_as_ephemeral=expected_send_as_ephemeral,
        expect_reaction_removal=expect_reaction_removal,
    )


def test_persona_access_denied_without_sender_falls_back_to_channel_message() -> None:
    _assert_access_denied_response(
        message_info=_make_slack_message_info(
            channel_type=ChannelType.PUBLIC_CHANNEL,
            sender_id=None,
        ),
        slack_channel_config=_make_slack_channel_config(),
        expected_receiver_ids=None,
        expected_thread_ts="111.222",
        expected_send_as_ephemeral=False,
        expect_reaction_removal=True,
    )


def test_configured_persona_missing_uses_configured_id_for_denial() -> None:
    slack_channel_config = _make_slack_channel_config()
    slack_channel_config.persona = None
    slack_channel_config.persona_id = 456

    _assert_access_denied_response(
        message_info=_make_slack_message_info(ChannelType.PUBLIC_CHANNEL),
        slack_channel_config=slack_channel_config,
        expected_receiver_ids=["U123"],
        expected_thread_ts="111.222",
        expected_send_as_ephemeral=True,
        expect_reaction_removal=True,
    )


def test_persona_access_denied_cancels_feedback_reminder() -> None:
    client = MagicMock()
    db_session = MagicMock()

    with (
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email", return_value=MagicMock()),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_persona_by_id",
            side_effect=ValueError("persona access denied"),
        ),
        patch(f"{_HANDLE_REGULAR_ANSWER}.respond_in_thread_or_channel"),
        patch(f"{_HANDLE_REGULAR_ANSWER}.update_emote_react"),
        patch(f"{_HANDLE_REGULAR_ANSWER}.handle_stream_message_objects"),
    ):
        result = handle_regular_answer(
            message_info=_make_slack_message_info(ChannelType.PUBLIC_CHANNEL),
            slack_channel_config=_make_slack_channel_config(),
            receiver_ids=None,
            client=client,
            channel="C123",
            logger=_mock_logger(),
            db_session=db_session,
            feedback_reminder_id="scheduled-reminder",
            should_respond_with_error_msgs=False,
        )

    assert result is False
    client.chat_deleteScheduledMessage.assert_called_once_with(
        channel="U123",
        scheduled_message_id="scheduled-reminder",
    )


def test_private_channel_non_ephemeral_generates_after_persona_access_check() -> None:
    user = MagicMock()
    anonymous_user = MagicMock()
    client = MagicMock()
    db_session = MagicMock()
    logger = _mock_logger()

    with (
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email", return_value=user),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_anonymous_user", return_value=anonymous_user
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_persona_by_id",
            return_value=_make_slack_channel_config().persona,
        ) as mock_get_persona_by_id,
        patch(f"{_HANDLE_REGULAR_ANSWER}.rate_limits", side_effect=_identity_decorator),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.retry_builder", side_effect=_identity_decorator
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_channel_name_from_id",
            return_value=("private-channel", False),
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.gather_stream",
            return_value=ChatBasicResponse(
                answer="answer",
                answer_citationless="answer",
                top_documents=[],
                error_msg=None,
                message_id=1,
                citation_info=[],
            ),
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.build_slack_response_blocks",
            return_value=[],
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.handle_stream_message_objects",
            return_value=iter(()),
        ) as mock_handle_stream_message_objects,
        patch(f"{_HANDLE_REGULAR_ANSWER}.respond_in_thread_or_channel") as mock_respond,
        patch(f"{_HANDLE_REGULAR_ANSWER}.update_emote_react") as mock_update_react,
    ):
        result = handle_regular_answer(
            message_info=_make_slack_message_info(ChannelType.PRIVATE_CHANNEL),
            slack_channel_config=_make_slack_channel_config(),
            receiver_ids=None,
            client=client,
            channel="C123",
            logger=logger,
            db_session=db_session,
            feedback_reminder_id=None,
        )

    assert result is False
    mock_get_persona_by_id.assert_called_once_with(
        persona_id=123,
        user=user,
        db_session=db_session,
        is_for_edit=False,
    )

    stream_call_kwargs = mock_handle_stream_message_objects.call_args.kwargs
    assert stream_call_kwargs["user"] is anonymous_user
    assert stream_call_kwargs["new_msg_req"].chat_session_info.persona_id == 123

    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["receiver_ids"] is None
    mock_update_react.assert_called_once()
    assert mock_update_react.call_args.kwargs["remove"] is True
