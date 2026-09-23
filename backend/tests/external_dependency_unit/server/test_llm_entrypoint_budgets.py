"""Admin token budgets apply to every entry point that spends LLM tokens.

`POST /search` (used by the MCP server and the public API), the Search UI and
the Slack bot spent tokens without running `check_token_rate_limits`, so a
caller over its budget in the web UI could keep spending through them. These
tests put the
tenant over a global budget in the real usage ledger and check that each entry
point refuses before it resolves or calls an LLM.
"""

from collections.abc import Callable, Generator
from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import delete
from sqlalchemy.orm import Session

import onyx.server.query_and_chat.token_limit as token_limit
from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest
from ee.onyx.server.query_and_chat.search_backend import handle_send_search_message
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import TokenRateLimit, User, UserUsage
from onyx.db.user_usage import get_token_window_start, record_user_usage
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.onyxbot.slack.handlers.handle_regular_answer import handle_regular_answer
from onyx.onyxbot.slack.models import (
    ChannelType,
    SlackContext,
    SlackMessageInfo,
    ThreadMessage,
)
from onyx.server.api_key_usage import check_api_key_usage
from onyx.server.features.search.api import router as search_router
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")

_HANDLE_REGULAR_ANSWER = "onyx.onyxbot.slack.handlers.handle_regular_answer"
_SEARCH_BACKEND = "ee.onyx.server.query_and_chat.search_backend"
_BUDGET_MESSAGE = "You've reached the usage budget for your organization."


def _fail_llm_resolution(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("an over-budget request resolved an LLM")


def _identity_decorator(
    *_args: object, **_kwargs: object
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    def _decorate(func: Callable[..., object]) -> Callable[..., object]:
        return func

    return _decorate


@pytest.fixture
def over_budget_user(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[User, None, None]:
    """A user whose recorded usage puts the tenant over a 1k-token global
    budget. The limit is injected so no global row lands in the shared DB."""
    user = create_test_user(db_session, "entrypoint-budget")
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        usage=LLMUsageRecord(
            model="entrypoint-budget-test-model",
            flow=LLMFlow.CHAT_RESPONSE.value,
            provider=None,
            input_tokens=1_500,
            output_tokens=500,
            cache_read_tokens=0,
            cost_cents=0.0,
            window_start=get_token_window_start(datetime.now(timezone.utc), 24),
        ),
    )
    db_session.commit()

    global_limit = TokenRateLimit(
        enabled=True,
        token_budget=1,
        cost_budget_cents=None,
        period_hours=24,
        scope=TokenRateLimitScope.GLOBAL,
    )
    monkeypatch.setattr(token_limit, "any_rate_limit_exists", lambda: True)
    monkeypatch.setattr(
        token_limit,
        "fetch_all_global_token_rate_limits",
        lambda **_: [global_limit],
    )

    yield user

    db_session.rollback()
    db_session.execute(delete(UserUsage).where(UserUsage.user_id == user.id))
    delete_test_user(db_session, user)
    db_session.commit()


def _search_route_dependency_calls() -> list[Callable[..., object]]:
    route = next(
        r
        for r in search_router.routes
        if isinstance(r, APIRoute) and r.path == "/search"
    )
    return [dep.call for dep in route.dependant.dependencies if dep.call is not None]


def test_search_checks_budget_before_counting_api_call(
    over_budget_user: User,
) -> None:
    calls = _search_route_dependency_calls()
    assert calls.index(check_token_rate_limits) < calls.index(check_api_key_usage)

    with pytest.raises(OnyxError) as exc_info:
        check_token_rate_limits(over_budget_user)

    assert exc_info.value.error_code is OnyxErrorCode.RATE_LIMITED
    assert exc_info.value.extra is not None
    assert exc_info.value.extra["scope"] == TokenRateLimitScope.GLOBAL.value


def test_search_ui_refuses_over_budget_llm_search(
    db_session: Session, over_budget_user: User
) -> None:
    with (
        patch(f"{_SEARCH_BACKEND}.get_default_llm", side_effect=_fail_llm_resolution),
        patch(
            f"{_SEARCH_BACKEND}.stream_search_query", side_effect=_fail_llm_resolution
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        handle_send_search_message(
            request=SendSearchQueryRequest(
                search_query="quarterly revenue", run_query_expansion=True
            ),
            user=over_budget_user,
            db_session=db_session,
        )

    assert exc_info.value.error_code is OnyxErrorCode.RATE_LIMITED


def test_search_ui_skips_budget_for_keyword_only_search(
    db_session: Session, over_budget_user: User
) -> None:
    with (
        patch(f"{_SEARCH_BACKEND}.get_default_llm", side_effect=_fail_llm_resolution),
        patch(f"{_SEARCH_BACKEND}.stream_search_query") as mock_stream,
        patch(f"{_SEARCH_BACKEND}.gather_search_stream") as mock_gather,
    ):
        response = handle_send_search_message(
            request=SendSearchQueryRequest(search_query="quarterly revenue"),
            user=over_budget_user,
            db_session=db_session,
        )

    mock_stream.assert_called_once()
    assert response is mock_gather.return_value


@pytest.mark.parametrize("reply_fails", [False, True])
def test_slack_bot_replies_with_budget_message_instead_of_answering(
    db_session: Session, over_budget_user: User, reply_fails: bool
) -> None:
    persona = MagicMock()
    persona.id = 123
    persona.name = "Channel Agent"
    persona.document_sets = []
    persona.tools = []
    slack_channel_config = MagicMock()
    slack_channel_config.persona = persona
    slack_channel_config.persona_id = persona.id
    slack_channel_config.channel_config = {"is_ephemeral": False}
    message_info = SlackMessageInfo(
        thread_messages=[ThreadMessage(message="answer this?", sender="User")],
        channel_to_respond="C123",
        msg_to_respond="111.222",
        thread_to_respond="111.222",
        sender_id="U123",
        email=over_budget_user.email,
        bypass_filters=True,
        is_slash_command=False,
        is_bot_dm=True,
        slack_context=SlackContext(
            channel_type=ChannelType.IM,
            channel_id="C123",
            user_id="U123",
            message_ts="111.222",
        ),
    )

    with (
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_user_by_email",
            return_value=over_budget_user,
        ),
        patch(f"{_HANDLE_REGULAR_ANSWER}.get_persona_by_id", return_value=persona),
        patch(f"{_HANDLE_REGULAR_ANSWER}.rate_limits", side_effect=_identity_decorator),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.retry_builder", side_effect=_identity_decorator
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.get_channel_name_from_id",
            return_value=("dm", True),
        ),
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.handle_stream_message_objects",
            side_effect=_fail_llm_resolution,
        ) as mock_stream,
        patch(
            f"{_HANDLE_REGULAR_ANSWER}.respond_in_thread_or_channel",
            side_effect=RuntimeError("slack down") if reply_fails else None,
        ) as mock_respond,
        patch(f"{_HANDLE_REGULAR_ANSWER}.update_emote_react") as mock_update_react,
        pytest.raises(RuntimeError) if reply_fails else nullcontext(),
    ):
        result = handle_regular_answer(
            message_info=message_info,
            slack_channel_config=slack_channel_config,
            receiver_ids=None,
            client=MagicMock(),
            channel="C123",
            logger=MagicMock(),
            db_session=db_session,
            feedback_reminder_id=None,
        )

    mock_update_react.assert_called_once()
    assert mock_update_react.call_args.kwargs["remove"] is True
    mock_stream.assert_not_called()
    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["text"] == _BUDGET_MESSAGE
    if not reply_fails:
        assert result is True
