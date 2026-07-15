"""The per-tenant Craft Slackbot service-account user, against a real Postgres.

get_or_create_craft_bot_user must: be idempotent (one bot user per tenant),
survive a concurrent-create race without clobbering the caller's session,
produce a user that can never log in, and stay invisible to the existing
user-facing listing queries (which already filter out API-key dummy users
by sentinel email domain).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from onyx.db.craft_bot_user import CRAFT_BOT_EMAIL
from onyx.db.craft_bot_user import get_or_create_craft_bot_user
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.users import delete_user_from_db
from onyx.db.users import get_all_accepted_users
from onyx.db.users import get_page_of_filtered_users
from onyx.db.users import get_user_by_email


def _delete_bot_user() -> None:
    with get_session_with_current_tenant() as session:
        bot_user = get_user_by_email(CRAFT_BOT_EMAIL, session)
        if bot_user is not None:
            delete_user_from_db(bot_user, session)


@pytest.fixture(autouse=True)
def _clean_bot_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Delete the singleton bot row before and after so every run exercises
    the creation path (not just the found-existing branch)."""
    _delete_bot_user()
    yield
    db_session.rollback()
    _delete_bot_user()


def test_get_or_create_is_idempotent(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    first = get_or_create_craft_bot_user(db_session)
    second = get_or_create_craft_bot_user(db_session)

    assert first.id == second.id
    assert first.email == CRAFT_BOT_EMAIL


def test_concurrent_create_race_returns_winner(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate losing the create race: another session inserts the bot row
    between this session's existence check and its insert."""
    real_helper = PasswordHelper()
    winner_ids: list[object] = []
    race_fired = False

    class _RacingPasswordHelper:
        def generate(self) -> str:
            return real_helper.generate()

        def hash(self, password: str) -> str:
            # One-shot: only the outer (losing) call triggers the race,
            # otherwise the winner's own call would recurse forever.
            nonlocal race_fired
            if not race_fired:
                race_fired = True
                with get_session_with_current_tenant() as other_session:
                    winner = get_or_create_craft_bot_user(other_session)
                    winner_ids.append(winner.id)
            return real_helper.hash(password)

    monkeypatch.setattr("onyx.db.craft_bot_user.PasswordHelper", _RacingPasswordHelper)

    loser_result = get_or_create_craft_bot_user(db_session)

    assert winner_ids == [loser_result.id]

    # The losing session must stay usable after the rolled-back insert.
    assert get_user_by_email(CRAFT_BOT_EMAIL, db_session) is not None
    db_session.commit()


def test_bot_user_cannot_log_in(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    bot_user = get_or_create_craft_bot_user(db_session)

    assert bot_user.account_type == AccountType.SERVICE_ACCOUNT
    assert not bot_user.oauth_accounts

    # The password is generated and discarded; no guess can verify.
    assert bot_user.hashed_password
    password_helper = PasswordHelper()
    verified, _ = password_helper.verify_and_update(
        "password", bot_user.hashed_password
    )
    assert verified is False


def test_bot_user_excluded_from_user_listings(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    bot_user = get_or_create_craft_bot_user(db_session)

    accepted_users = get_all_accepted_users(db_session)
    assert bot_user.id not in {user.id for user in accepted_users}

    paginated_users = get_page_of_filtered_users(db_session, page_size=1000, page_num=0)
    assert bot_user.id not in {user.id for user in paginated_users}
