"""Which spending limit scopes hold each kind of principal: service accounts
answer to shared pools but never to a per-person budget."""

from uuid import UUID, uuid4

from onyx.configs.constants import (
    ANONYMOUS_USER_UUID,
    DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN,
    TokenRateLimitScope,
)
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.server.query_and_chat.token_limit import spend_limit_scopes

GLOBAL = TokenRateLimitScope.GLOBAL
USER_GROUP = TokenRateLimitScope.USER_GROUP


def test_person_is_held_to_every_scope() -> None:
    user = User(
        id=uuid4(), email="person@example.com", account_type=AccountType.STANDARD
    )

    assert spend_limit_scopes(user) == frozenset(TokenRateLimitScope)


def test_service_account_is_held_to_pools_only() -> None:
    user = User(
        id=uuid4(),
        email="service@example.com",
        account_type=AccountType.SERVICE_ACCOUNT,
    )

    assert spend_limit_scopes(user) == {GLOBAL, USER_GROUP}


def test_api_key_user_is_held_to_pools_only() -> None:
    user = User(
        id=uuid4(),
        email=f"key@{DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN}",
        account_type=AccountType.STANDARD,
    )

    assert spend_limit_scopes(user) == {GLOBAL, USER_GROUP}


def test_anonymous_user_is_held_to_the_workspace_pool_only() -> None:
    user = User(id=UUID(ANONYMOUS_USER_UUID), email="anonymous@example.com")

    assert spend_limit_scopes(user) == {GLOBAL}
