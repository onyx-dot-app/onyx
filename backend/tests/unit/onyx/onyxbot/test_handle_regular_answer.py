"""Slack answer handling: references, access checks, and usage attribution."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from slack_sdk.errors import SlackApiError

from onyx.chat.models import ChatBasicResponse, ChatStreamError
from onyx.context.search.models import Tag
from onyx.onyxbot.slack.constants import SLACK_CHANNEL_REF_PATTERN
from onyx.onyxbot.slack.handlers.handle_regular_answer import (
    SLACK_ANSWER_FAILED_MESSAGE,
    SLACK_NO_ANSWER_MESSAGE,
    SLACK_PERSONA_ACCESS_DENIED_MESSAGE,
    handle_regular_answer,
    resolve_channel_references,
)
from onyx.onyxbot.slack.models import (
    ChannelType,
    SlackContext,
    SlackMessageInfo,
    ThreadMessage,
)
from onyx.onyxbot.slack.utils import update_emote_react
from shared_configs.contextvars import get_current_user_id

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
    persona.tools = []

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


@pytest.mark.parametrize("has_mapped_user", [True, False])
def test_private_channel_non_ephemeral_attributes_usage(
    has_mapped_user: bool,
) -> None:
    user = MagicMock() if has_mapped_user else None
    if user is not None:
        user.id = uuid4()
    service_user = MagicMock()
    service_user.id = uuid4()
    usage_user = user or service_user
    anonymous_user = MagicMock()
    client = MagicMock()
    db_session = MagicMock()
    logger = _mock_logger()
    observed_user_ids: list[str | None] = []

    def _gather_stream(_: object) -> ChatBasicResponse:
        observed_user_ids.append(get_current_user_id())
        return ChatBasicResponse(
            answer="answer",
            answer_citationless="answer",
            top_documents=[],
            error_msg=None,
            message_id=1,
            citation_info=[],
        )

    with (
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email", return_value=user),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_or_create_slack_service_account",
            return_value=service_user,
        ) as mock_get_service_account,
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
            side_effect=_gather_stream,
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
        user=user or anonymous_user,
        db_session=db_session,
        is_for_edit=False,
    )
    if has_mapped_user:
        mock_get_service_account.assert_not_called()
    else:
        mock_get_service_account.assert_called_once_with(db_session)

    stream_call_kwargs = mock_handle_stream_message_objects.call_args.kwargs
    assert stream_call_kwargs["user"] is anonymous_user
    assert stream_call_kwargs["new_msg_req"].chat_session_info.persona_id == 123
    assert observed_user_ids == [str(usage_user.id)]
    assert get_current_user_id() is None

    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["receiver_ids"] is None
    mock_update_react.assert_called_once()
    assert mock_update_react.call_args.kwargs["remove"] is True


@pytest.mark.parametrize(
    "has_search_tool,search_available,search_enabled,expected_forced_id",
    [
        (True, True, True, 77),  # persona has SearchTool and it is usable -> forced
        (True, False, True, None),  # SearchTool attached but unavailable -> not forced
        (True, True, False, None),  # SearchTool attached but disabled -> not forced
        (False, True, True, None),  # persona without SearchTool -> not forced
    ],
)
def test_search_tool_forced_only_when_usable(
    has_search_tool: bool,
    search_available: bool,
    search_enabled: bool,
    expected_forced_id: int | None,
) -> None:
    """Slack answers force the persona's search tool on the first LLM cycle
    (regression for the #7399 refactor dropping guaranteed retrieval), but
    never for personas without a usable search tool."""
    slack_channel_config = _make_slack_channel_config()
    persona = slack_channel_config.persona
    if has_search_tool:
        search_tool = MagicMock()
        search_tool.id = 77
        search_tool.in_code_tool_id = "SearchTool"
        search_tool.enabled = search_enabled
        persona.tools = [search_tool]

    user = MagicMock()
    user.id = uuid4()

    def _gather_stream(_: object) -> ChatBasicResponse:
        return ChatBasicResponse(
            answer="answer",
            answer_citationless="answer",
            top_documents=[],
            error_msg=None,
            message_id=1,
            citation_info=[],
        )

    with (
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email", return_value=user),
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_anonymous_user", return_value=MagicMock()),
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_persona_by_id", return_value=persona),
        patch(f"{_HANDLE_REGULAR_ANSWER}.rate_limits", side_effect=_identity_decorator),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.retry_builder", side_effect=_identity_decorator
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_channel_name_from_id",
            return_value=("channel", False),
        ),
        patch(f"{_HANDLE_REGULAR_ANSWER}.gather_stream", side_effect=_gather_stream),
        patch(f"{_HANDLE_REGULAR_ANSWER}.build_slack_response_blocks", return_value=[]),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.handle_stream_message_objects",
            return_value=iter(()),
        ) as mock_handle_stream_message_objects,
        patch(f"{_HANDLE_REGULAR_ANSWER}.SearchTool") as mock_search_tool_cls,
        patch(f"{_HANDLE_REGULAR_ANSWER}.respond_in_thread_or_channel"),
        patch(f"{_HANDLE_REGULAR_ANSWER}.update_emote_react"),
    ):
        mock_search_tool_cls.is_available.return_value = search_available
        handle_regular_answer(
            message_info=_make_slack_message_info(ChannelType.IM),
            slack_channel_config=slack_channel_config,
            receiver_ids=None,
            client=MagicMock(),
            channel="C123",
            logger=_mock_logger(),
            db_session=MagicMock(),
            feedback_reminder_id=None,
        )

    stream_call_kwargs = mock_handle_stream_message_objects.call_args.kwargs
    assert stream_call_kwargs["new_msg_req"].forced_tool_id == expected_forced_id


# ---------------------------------------------------------------------------
# Failure and no-answer notices
# ---------------------------------------------------------------------------


def _answer(
    error_msg: str | None = None,
    error_code: str | None = None,
    answer: str = "answer",
) -> ChatBasicResponse:
    return ChatBasicResponse(
        answer=answer,
        answer_citationless=answer,
        top_documents=[],
        error_msg=error_msg,
        error_code=error_code,
        message_id=1,
        citation_info=[],
    )


def _run_regular_answer(
    gather_stream: Callable[[object], ChatBasicResponse],
    slack_channel_config: MagicMock | None = None,
    message_info: SlackMessageInfo | None = None,
    respond_side_effect: Exception | list[Exception | None] | None = None,
    react_side_effect: Exception | None = None,
    receiver_ids: list[str] | None = None,
    **handler_kwargs: bool,
) -> tuple[bool, MagicMock, MagicMock]:
    """Run the handler with its collaborators patched. Return the result, the reply mock and the react mock."""
    with (
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email", return_value=MagicMock()),
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_anonymous_user", return_value=MagicMock()),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_persona_by_id",
            return_value=_make_slack_channel_config().persona,
        ),
        patch(f"{_HANDLE_REGULAR_ANSWER}.rate_limits", side_effect=_identity_decorator),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.retry_builder", side_effect=_identity_decorator
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_channel_name_from_id",
            return_value=("some-channel", False),
        ),
        patch(f"{_HANDLE_REGULAR_ANSWER}.gather_stream", side_effect=gather_stream),
        patch(f"{_HANDLE_REGULAR_ANSWER}.build_slack_response_blocks", return_value=[]),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.handle_stream_message_objects",
            return_value=iter(()),
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.respond_in_thread_or_channel",
            side_effect=respond_side_effect,
        ) as mock_respond,
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.update_emote_react",
            side_effect=react_side_effect,
        ) as mock_update_react,
    ):
        result = handle_regular_answer(
            message_info=message_info
            or _make_slack_message_info(ChannelType.PRIVATE_CHANNEL),
            slack_channel_config=slack_channel_config or _make_slack_channel_config(),
            receiver_ids=receiver_ids,
            client=MagicMock(),
            channel="C123",
            logger=_mock_logger(),
            db_session=MagicMock(),
            feedback_reminder_id=None,
            **handler_kwargs,
        )
    return result, mock_respond, mock_update_react


def _overheard_message_info() -> SlackMessageInfo:
    message_info = _make_slack_message_info(ChannelType.PRIVATE_CHANNEL)
    message_info.bypass_filters = False
    return message_info


def _citation_filter_config() -> MagicMock:
    config = _make_slack_channel_config()
    config.channel_config = {
        "is_ephemeral": False,
        "answer_filters": ["well_answered_postfilter"],
    }
    return config


_CREDIT_ERROR = "anthropic quota exceeded: Your credit balance is too low to access the Anthropic API."


def test_classified_provider_error_is_stated_to_the_user() -> None:
    result, mock_respond, mock_update_react = _run_regular_answer(
        lambda _: _answer(_CREDIT_ERROR, "BUDGET_EXCEEDED", answer=""),
        should_respond_with_error_msgs=False,
    )

    assert result is True
    mock_respond.assert_called_once()
    assert _CREDIT_ERROR in mock_respond.call_args.kwargs["text"]
    assert "Onyx administrator" in mock_respond.call_args.kwargs["text"]
    assert mock_respond.call_args.kwargs["thread_ts"] == "111.222"
    assert mock_update_react.call_args.kwargs["remove"] is True


@pytest.mark.parametrize("error_code", ["UNKNOWN_ERROR", "VALIDATION_ERROR", None])
def test_unclassified_pipeline_error_text_does_not_reach_slack(
    error_code: str | None,
) -> None:
    """The pipeline forwards the raw exception text for these, which can name internals."""
    _, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(
            'relation "tenant_abc.tool" does not exist', error_code, answer=""
        ),
        should_respond_with_error_msgs=False,
    )

    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["text"] == SLACK_ANSWER_FAILED_MESSAGE


def test_unexpected_error_gets_the_generic_notice() -> None:
    def _boom(_: object) -> ChatBasicResponse:
        raise ValueError("internal detail")

    result, mock_respond, _ = _run_regular_answer(
        _boom, should_respond_with_error_msgs=False
    )

    assert result is True
    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["text"] == SLACK_ANSWER_FAILED_MESSAGE


def test_debug_flag_shows_the_raw_exception() -> None:
    def _boom(_: object) -> ChatBasicResponse:
        raise ValueError("internal detail")

    _, mock_respond, _ = _run_regular_answer(_boom, should_respond_with_error_msgs=True)

    assert "internal detail" in mock_respond.call_args.kwargs["text"]


def test_notice_that_cannot_be_sent_does_not_stop_the_cleanup() -> None:
    result, _, mock_update_react = _run_regular_answer(
        lambda _: _answer(_CREDIT_ERROR, "BUDGET_EXCEEDED", answer=""),
        respond_side_effect=SlackApiError("channel_not_found", response=MagicMock()),
        should_respond_with_error_msgs=False,
    )

    assert result is True
    assert mock_update_react.call_args.kwargs["remove"] is True


def test_reaction_cleanup_cannot_raise() -> None:
    """It runs after the user has their outcome. An escaped error would reach the
    listener, which would report a second failure."""
    client = MagicMock()
    client.reactions_remove.side_effect = TimeoutError("slack did not respond")

    update_emote_react(
        emoji="eyes", channel="C123", message_ts="111.222", remove=True, client=client
    )

    client.reactions_remove.assert_called_once()


@pytest.mark.parametrize(
    "error_code,error_text",
    [
        (
            "INSUFFICIENT_PERMISSIONS",
            "User does not have access to document sets: ['Docs']",
        ),
        ("LLM_NOT_CONFIGURED", "No default LLM model found"),
    ],
)
def test_setup_error_raised_by_gather_stream_is_stated(
    error_code: str, error_text: str
) -> None:
    """These come before the message ID exists, so gather_stream raises them."""

    def _raise(_: object) -> ChatBasicResponse:
        raise ChatStreamError(error_text, error_code)

    _, mock_respond, _ = _run_regular_answer(
        _raise, should_respond_with_error_msgs=False
    )

    mock_respond.assert_called_once()
    assert error_text in mock_respond.call_args.kwargs["text"]


@pytest.mark.parametrize(
    "error_code",
    ["BAD_REQUEST", "SERVICE_UNAVAILABLE", "NOT_FOUND", "PERMISSION_DENIED"],
)
def test_codes_whose_text_carries_the_raw_exception_are_not_stated(
    error_code: str,
) -> None:
    _, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(
            "Bad request: {'input': 'system prompt and retrieved text'}",
            error_code,
            answer="",
        ),
        should_respond_with_error_msgs=False,
    )

    assert mock_respond.call_args.kwargs["text"] == SLACK_ANSWER_FAILED_MESSAGE


def test_rejected_answer_post_falls_back_to_a_plain_text_notice() -> None:
    result, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(),
        respond_side_effect=[
            SlackApiError("invalid_blocks", response={"error": "invalid_blocks"}),
            None,
        ],
        should_respond_with_error_msgs=False,
    )

    assert result is True
    assert mock_respond.call_count == 2
    assert mock_respond.call_args.kwargs["text"] == SLACK_ANSWER_FAILED_MESSAGE
    assert "blocks" not in mock_respond.call_args.kwargs


def test_timed_out_answer_post_gets_no_failure_notice() -> None:
    """Slack can accept a post and the client can still time out reading the reply,
    so only a rejection from Slack proves that nothing was delivered."""
    _, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(),
        respond_side_effect=TimeoutError("slack did not respond"),
        should_respond_with_error_msgs=False,
    )

    mock_respond.assert_called_once()


def test_partly_delivered_answer_gets_no_failure_notice() -> None:
    """With several receivers, one can have the answer before a later post fails."""
    _, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(),
        respond_side_effect=SlackApiError(
            "invalid_blocks", response={"error": "invalid_blocks"}
        ),
        receiver_ids=["U1", "U2"],
        should_respond_with_error_msgs=False,
    )

    mock_respond.assert_called_once()


def test_empty_answer_is_stated_when_the_sender_addressed_the_bot() -> None:
    result, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(answer=""),
        should_respond_with_error_msgs=False,
        disable_docs_only_answer=True,
    )

    assert result is True
    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["text"] == SLACK_NO_ANSWER_MESSAGE


def test_empty_answer_stays_quiet_for_an_overheard_message() -> None:
    result, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(answer=""),
        message_info=_overheard_message_info(),
        should_respond_with_error_msgs=False,
        disable_docs_only_answer=True,
    )

    assert result is True
    mock_respond.assert_not_called()


def test_citation_filter_drops_an_overheard_answer_quietly() -> None:
    result, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(),
        slack_channel_config=_citation_filter_config(),
        message_info=_overheard_message_info(),
        should_respond_with_error_msgs=False,
    )

    assert result is True
    mock_respond.assert_not_called()


def test_citation_filter_does_not_apply_to_a_dm() -> None:
    """A DM is addressed to the bot as much as a tag is, and tags skip the filters."""
    message_info = _make_slack_message_info(ChannelType.IM, is_bot_dm=True)
    message_info.bypass_filters = False

    result, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(),
        slack_channel_config=_citation_filter_config(),
        message_info=message_info,
        should_respond_with_error_msgs=False,
    )

    assert result is False
    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["blocks"] == []


def test_stated_error_is_shown_literally_in_slack() -> None:
    """Slack reads message text as mrkdwn. An error's own characters must not
    become a mention, a link or formatting."""
    hostile = "See <!channel> and <https://evil.test|this> & _that_ *now* ```x```"

    _, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(hostile, "BUDGET_EXCEEDED", answer=""),
        should_respond_with_error_msgs=False,
    )

    text: str = mock_respond.call_args.kwargs["text"]
    assert "<!channel>" not in text
    assert "&lt;!channel&gt;" in text
    assert "&amp; _that_ *now*" in text
    # One code block, which the error's own backticks cannot close early.
    assert text.count("```") == 2


def test_rejection_that_is_not_about_the_payload_gets_no_failure_notice() -> None:
    """The post helper retries and raises only its last error. An earlier attempt
    can have been delivered, and a rate limit on a later one does not disprove it."""
    _, mock_respond, _ = _run_regular_answer(
        lambda _: _answer(),
        respond_side_effect=SlackApiError(
            "ratelimited", response={"error": "ratelimited"}
        ),
        should_respond_with_error_msgs=False,
    )

    mock_respond.assert_called_once()
