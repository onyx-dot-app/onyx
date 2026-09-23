"""Service accounts are held to global budgets only.

A service account stands in for many callers: the Slack bot charges every
Slack user who has no Onyx account to one, and API keys are service accounts
too. A per-user budget on that single principal would throttle all of those
callers as one user, so the Slack bot would stop answering all of them at
once. Only API keys whose email matched the API-key pattern were exempt.
"""

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

import ee.onyx.server.query_and_chat.token_limit as ee_token_limit
import onyx.server.query_and_chat.token_limit as token_limit
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.enums import AccountType
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import TokenRateLimit, User, UserUsage
from onyx.db.user_usage import get_token_window_start, record_user_usage
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tracing.flows import LLMFlow
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")


def _token_limit(scope: TokenRateLimitScope) -> TokenRateLimit:
    # token_budget is in thousands, so 1 means 1,000 tokens.
    return TokenRateLimit(
        enabled=True,
        token_budget=1,
        cost_budget_cents=None,
        period_hours=24,
        scope=scope,
    )


def _record_over_budget_usage(db_session: Session, user: User) -> None:
    record_user_usage(
        db_session=db_session,
        user_id=str(user.id),
        usage=LLMUsageRecord(
            model="service-account-budget-test-model",
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


@pytest.fixture
def users_over_a_per_user_budget(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[User, User], None, None]:
    """A standard user and a service account, each over a 1k-token per-user
    budget. Limits are injected so no rows land in the shared DB, and group and
    global limits are cleared so leftover rows from other suites cannot trip."""
    standard = create_test_user(db_session, "budget-scope-standard")
    service = create_test_user(
        db_session, "budget-scope-service", account_type=AccountType.SERVICE_ACCOUNT
    )
    for user in (standard, service):
        _record_over_budget_usage(db_session, user)

    monkeypatch.setattr(
        ee_token_limit,
        "fetch_all_user_token_rate_limits",
        lambda **_: [_token_limit(TokenRateLimitScope.USER)],
    )
    monkeypatch.setattr(
        ee_token_limit, "_user_is_rate_limited_by_group", lambda _: None
    )
    monkeypatch.setattr(
        token_limit, "fetch_all_global_token_rate_limits", lambda **_: []
    )

    yield standard, service

    db_session.rollback()
    db_session.execute(
        delete(UserUsage).where(UserUsage.user_id.in_([standard.id, service.id]))
    )
    delete_test_user(db_session, standard, service)
    db_session.commit()


def test_standard_user_over_per_user_budget_is_limited(
    users_over_a_per_user_budget: tuple[User, User],
) -> None:
    standard, _ = users_over_a_per_user_budget

    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._check_token_rate_limits(standard)

    assert exc_info.value.error_code is OnyxErrorCode.RATE_LIMITED
    assert exc_info.value.extra is not None
    assert exc_info.value.extra["scope"] == TokenRateLimitScope.USER.value


def test_service_account_is_not_held_to_per_user_budget(
    users_over_a_per_user_budget: tuple[User, User],
) -> None:
    _, service = users_over_a_per_user_budget

    ee_token_limit._check_token_rate_limits(service)


def test_service_account_is_still_held_to_global_budget(
    users_over_a_per_user_budget: tuple[User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, service = users_over_a_per_user_budget
    monkeypatch.setattr(
        token_limit,
        "fetch_all_global_token_rate_limits",
        lambda **_: [_token_limit(TokenRateLimitScope.GLOBAL)],
    )

    with pytest.raises(OnyxError) as exc_info:
        ee_token_limit._check_token_rate_limits(service)

    assert exc_info.value.error_code is OnyxErrorCode.RATE_LIMITED
    assert exc_info.value.extra is not None
    assert exc_info.value.extra["scope"] == TokenRateLimitScope.GLOBAL.value
