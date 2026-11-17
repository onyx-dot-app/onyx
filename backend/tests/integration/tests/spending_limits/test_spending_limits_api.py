"""The spending limits admin API end to end: cards round-trip, invalid cards are
rejected, a group's per-member limit on one model blocks only that model in a
chat turn, and the effective-limits view names where each budget comes from."""

import os
import time
from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ModelConfiguration, UserUsage
from onyx.llm.override_models import LLMOverride
from tests.common.models import CI_OPENAI_MODEL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.spending_limits import (
    SpendingLimitsManager,
)
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EE_TESTS", "").lower() != "true",
    reason="Spending limits are an enterprise feature",
)

# Drain thread flushes usage on a ~2s interval; give it generous headroom.
_USAGE_TIMEOUT_SECONDS = 45
_TINY_COST_CENTS = 0.001
_SECOND_MODEL = "gpt-5-mini"


@pytest.fixture
def clear_workspace_cards(admin_user: DATestUser) -> Generator[None, None, None]:
    yield
    for path in ("workspace/pool", "workspace/per-user"):
        SpendingLimitsManager.set_card(path, [], admin_user)


def _model_configuration_id(provider_id: int, name: str) -> int:
    with get_session_with_current_tenant() as db_session:
        return db_session.execute(
            select(ModelConfiguration.id).where(
                ModelConfiguration.llm_provider_id == provider_id,
                ModelConfiguration.name == name,
            )
        ).scalar_one()


def _wait_for_model_usage(model_configuration_id: int) -> None:
    deadline = time.monotonic() + _USAGE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with get_session_with_current_tenant() as db_session:
            if db_session.scalar(
                select(UserUsage.id).where(
                    UserUsage.model_configuration_id == model_configuration_id
                )
            ):
                return
        time.sleep(1)
    raise AssertionError("the usage recorder never landed a row for the model")


def test_cards_round_trip_and_reject_invalid_limits(
    admin_user: DATestUser,
    clear_workspace_cards: None,  # noqa: ARG001
) -> None:
    provider = LLMProviderManager.create(user_performing_action=admin_user)
    model_id = provider.model_configuration_ids[0]

    card = SpendingLimitsManager.set_card(
        "workspace/per-user",
        [
            {"period": "DAILY", "cost_budget_cents": 500},
            {
                "period": "MONTHLY",
                "token_budget": 2_000,
                "model_configuration_id": model_id,
            },
            {"period": "MONTHLY", "action": "ALERT_ONLY", "threshold_percent": 80},
        ],
        admin_user,
    )
    assert card.enabled
    assert {(limit.period, limit.model_configuration_id) for limit in card.limits} == {
        ("DAILY", None),
        ("MONTHLY", model_id),
        ("MONTHLY", None),
    }
    model_limit = next(limit for limit in card.limits if limit.model_configuration_id)
    assert model_limit.model_name is not None

    everything = SpendingLimitsManager.get_all(admin_user)
    assert len(everything.workspace_per_user.limits) == 3

    duplicate = SpendingLimitsManager.put_card(
        "workspace/pool",
        [
            {"period": "DAILY", "cost_budget_cents": 500},
            {"period": "DAILY", "token_budget": 10},
        ],
        admin_user,
    )
    assert duplicate.status_code == 422

    unknown_model = SpendingLimitsManager.put_card(
        "workspace/pool",
        [{"period": "DAILY", "cost_budget_cents": 500, "model_configuration_id": -1}],
        admin_user,
    )
    assert unknown_model.status_code == 400

    percentage_block = SpendingLimitsManager.put_card(
        "workspace/pool",
        [{"period": "DAILY", "threshold_percent": 50}],
        admin_user,
    )
    assert percentage_block.status_code == 422


def test_group_member_model_limit_blocks_only_that_model(
    admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        user_performing_action=admin_user, model_names=[_SECOND_MODEL]
    )
    limited_model = _model_configuration_id(provider.id, CI_OPENAI_MODEL)
    member = UserManager.create(name=f"spending_limit_member_{uuid4().hex[:8]}")
    group = UserGroupManager.create(
        user_performing_action=admin_user, user_ids=[member.id]
    )
    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user, user_groups_to_check=[group]
    )
    SpendingLimitsManager.set_card(
        f"groups/{group.id}/per-member",
        [
            {
                "period": "DAILY",
                "cost_budget_cents": _TINY_COST_CENTS,
                "model_configuration_id": limited_model,
            }
        ],
        admin_user,
    )

    session = ChatSessionManager.create(user_performing_action=member)
    first = ChatSessionManager.send_message(
        chat_session_id=session.id,
        message="Reply with a single word.",
        user_performing_action=member,
    )
    assert first.error is None, first.error
    _wait_for_model_usage(limited_model)

    blocked = ChatSessionManager.send_message(
        chat_session_id=session.id,
        message="Again.",
        user_performing_action=member,
        parent_message_id=first.assistant_message_id,
    )
    assert blocked.error is not None
    assert blocked.error.error_code == "RATE_LIMITED"
    assert blocked.error.details["scope"] == "user_group_member"
    assert blocked.error.details["model"]

    other_session = ChatSessionManager.create(user_performing_action=member)
    other_model = ChatSessionManager.send_message(
        chat_session_id=other_session.id,
        message="Reply with a single word.",
        user_performing_action=member,
        llm_override=LLMOverride(
            model_provider=provider.name, model_version=_SECOND_MODEL
        ),
    )
    assert other_model.error is None, other_model.error

    effective = SpendingLimitsManager.get_effective(member.id, admin_user)
    assert [
        (limit.model_configuration_id, limit.scope, limit.user_group_id)
        for limit in effective.allowances
    ] == [(limited_model, "user_group_member", group.id)]
