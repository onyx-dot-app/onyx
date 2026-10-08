"""A downgrade to Community switches off the paid features that act without a
request: nothing below their tier could turn them off afterwards. The database
tests roll their transaction back."""

from collections.abc import Generator
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ee.onyx.db.community_downgrade import disable_paid_features__no_commit
from ee.onyx.server.enterprise_settings.models import EnterpriseSettings
from ee.onyx.server.enterprise_settings.store import (
    get_logo_filename,
    get_logotype_filename,
    load_analytics_script,
)
from ee.onyx.server.enterprise_settings.store import load_settings as load_branding
from ee.onyx.server.enterprise_settings.store import reset_settings as reset_branding
from ee.onyx.server.enterprise_settings.store import store_settings as store_branding
from onyx.configs.constants import (
    DISCORD_SERVICE_API_KEY_NAME,
    KV_CUSTOM_ANALYTICS_SCRIPT_KEY,
    FileOrigin,
    TokenRateLimitScope,
)
from onyx.db.enums import AccountType, HookFailStrategy, HookPoint, UserFileStatus
from onyx.db.models import (
    ApiKey,
    Hook,
    ScimToken,
    StandardAnswer,
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User,
    UserFile,
    UserGroup,
)
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.server.settings.store import (
    clear_chat_retention,
    load_settings,
    store_settings,
)


def _make_user(db_session: Session, account_type: AccountType) -> User:
    user = User(
        id=uuid4(),
        email=f"downgrade-{uuid4().hex[:8]}@example.com",
        hashed_password="unused",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        account_type=account_type,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_api_key(db_session: Session, name: str, owner: User | None) -> ApiKey:
    """A key with its own synthetic user, which owns an uploaded file."""
    key_user = _make_user(db_session, AccountType.SERVICE_ACCOUNT)
    db_session.add(
        UserFile(
            id=uuid4(),
            user_id=key_user.id,
            file_id=f"downgrade-{uuid4().hex[:8]}",
            name="upload.txt",
            file_type="text/plain",
            status=UserFileStatus.COMPLETED,
        )
    )
    api_key = ApiKey(
        name=name,
        hashed_api_key=uuid4().hex,
        api_key_display=uuid4().hex,
        user_id=key_user.id,
        owner_id=owner.id if owner else None,
    )
    db_session.add(api_key)
    db_session.flush()
    return api_key


@pytest.mark.usefixtures("tenant_context")
def test_paid_features_are_switched_off(db_session: Session) -> None:
    try:
        # Only one live hook per hook point may exist.
        db_session.execute(update(Hook).values(deleted=True))
        creator = _make_user(db_session, AccountType.STANDARD)
        hook = Hook(
            name="downgrade",
            hook_point=HookPoint.QUERY_PROCESSING,
            fail_strategy=HookFailStrategy.HARD,
            is_active=True,
        )
        standard_answer = StandardAnswer(
            keyword=f"downgrade-{uuid4().hex[:8]}",
            answer="answer",
            active=True,
            match_regex=False,
            match_any_keywords=False,
        )
        rate_limit = TokenRateLimit(
            token_budget=1, period_hours=1, scope=TokenRateLimitScope.GLOBAL
        )
        group_rate_limit = TokenRateLimit(
            token_budget=1, period_hours=1, scope=TokenRateLimitScope.USER_GROUP
        )
        group = UserGroup(name=f"downgrade-{uuid4().hex[:8]}")
        db_session.add_all([hook, standard_answer, rate_limit, group_rate_limit, group])
        db_session.flush()
        db_session.add(
            TokenRateLimit__UserGroup(
                rate_limit_id=group_rate_limit.id, user_group_id=group.id
            )
        )
        scim_token = ScimToken(
            name="downgrade",
            hashed_token=uuid4().hex,
            token_display="onyx_scim_...",
            created_by_id=creator.id,
            is_active=True,
        )
        db_session.add(scim_token)
        db_session.flush()
        key = _make_api_key(db_session, "downgrade", owner=creator)
        # Made through the first key, so that key's user owns it.
        nested_key = _make_api_key(db_session, "downgrade-nested", owner=key.user)
        # The bot creates its key with no owner.
        discord_key = _make_api_key(
            db_session, DISCORD_SERVICE_API_KEY_NAME, owner=None
        )
        # An admin's key that only shares the bot key's name.
        namesake_key = _make_api_key(
            db_session, DISCORD_SERVICE_API_KEY_NAME, owner=creator
        )
        removed_key_ids = [key.id, nested_key.id, namesake_key.id]
        removed_user_ids = [key.user_id, nested_key.user_id, namesake_key.user_id]
        discord_key_id = discord_key.id
        rate_limit_ids = [rate_limit.id, group_rate_limit.id]

        disable_paid_features__no_commit(db_session)

        db_session.expire_all()
        assert db_session.scalars(select(Hook.deleted).where(Hook.id == hook.id)).one()
        assert not db_session.scalars(
            select(Hook.is_active).where(Hook.id == hook.id)
        ).one()
        assert not db_session.scalars(
            select(StandardAnswer.active).where(StandardAnswer.id == standard_answer.id)
        ).one()
        assert not db_session.scalars(
            select(ScimToken.is_active).where(ScimToken.id == scim_token.id)
        ).one()
        assert not db_session.scalars(
            select(TokenRateLimit.id).where(TokenRateLimit.id.in_(rate_limit_ids))
        ).all()
        assert not db_session.scalars(
            select(ApiKey.id).where(ApiKey.id.in_(removed_key_ids))
        ).all()
        # The Discord bot keeps its service key.
        assert db_session.scalars(
            select(ApiKey.id).where(ApiKey.id == discord_key_id)
        ).all()
        # The synthetic user behind a key goes with it.
        assert not db_session.scalars(
            select(User.__table__.c.id).where(User.__table__.c.id.in_(removed_user_ids))
        ).all()
        # Their uploads stay, with no owner.
        assert len(
            db_session.scalars(
                select(UserFile.id).where(
                    UserFile.name == "upload.txt", UserFile.user_id.is_(None)
                )
            ).all()
        ) >= len(removed_user_ids)
    finally:
        db_session.rollback()


@pytest.fixture
def restore_settings(
    # Initializes the engine the stores read through.
    db_session: Session,  # noqa: ARG001
) -> Generator[None, None, None]:
    """The settings stores commit on their own, so put back what was there.
    Logo files are not restored: run this against a disposable file store."""
    settings = load_settings()
    branding = load_branding()
    analytics_script = load_analytics_script()
    yield
    store_settings(settings)
    store_branding(branding)
    if analytics_script is not None:
        get_kv_store().store(KV_CUSTOM_ANALYTICS_SCRIPT_KEY, analytics_script)


@pytest.mark.usefixtures("tenant_context", "restore_settings")
def test_chat_retention_is_cleared() -> None:
    settings = load_settings()
    settings.maximum_chat_retention_days = 30
    store_settings(settings)

    clear_chat_retention()

    assert load_settings().maximum_chat_retention_days is None


@pytest.mark.usefixtures("tenant_context", "restore_settings")
def test_branding_is_reset() -> None:
    store_branding(EnterpriseSettings(application_name="Acme Search"))
    get_kv_store().store(KV_CUSTOM_ANALYTICS_SCRIPT_KEY, "console.log('x')")
    file_store: FileStore = get_default_file_store()
    logo_ids: list[str] = [get_logo_filename(), get_logotype_filename()]
    for file_id in logo_ids:
        file_store.save_file(
            content=BytesIO(b"logo"),
            display_name=file_id,
            file_origin=FileOrigin.OTHER,
            file_type="image/png",
            file_id=file_id,
        )

    reset_branding()

    assert load_branding() == EnterpriseSettings()
    assert load_analytics_script() is None
    for file_id in logo_ids:
        assert not file_store.has_file(file_id, FileOrigin.OTHER, "image/png")
    # Nothing left to remove is not an error.
    reset_branding()
