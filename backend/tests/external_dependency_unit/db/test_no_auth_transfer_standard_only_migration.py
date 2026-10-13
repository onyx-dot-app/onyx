"""Migration c9d4c7acacdd limits the no-auth data transfer trigger from
f7ca3e2f45d9 to STANDARD users. The test installs the original trigger, runs
the migration, inserts non-registrant rows and then a real user, all inside
one transaction that it rolls back."""

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.configs.constants import (
    NO_AUTH_PLACEHOLDER_USER_EMAIL,
    NO_AUTH_PLACEHOLDER_USER_UUID,
)
from onyx.db.api_key import get_api_key_fake_email
from onyx.db.enums import AccountType
from onyx.db.models import ChatSession, User

_VERSIONS = Path(__file__).parents[3] / "alembic/versions"
_ORIGINAL_MIGRATION = _VERSIONS / "f7ca3e2f45d9_migrate_no_auth_data_to_placeholder.py"
_FIX_MIGRATION = _VERSIONS / "c9d4c7acacdd_restrict_no_auth_data_transfer_to_.py"


def _load(path: Path, name: str) -> ModuleType:
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _add_user(
    db_session: Session, account_type: AccountType, email: str | None = None
) -> User:
    user = User(
        id=uuid4(),
        email=email or f"no-auth-{uuid4().hex[:8]}@example.com",
        hashed_password="unused",
        is_active=True,
        account_type=account_type,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _owner(db_session: Session, chat_session_id: UUID) -> UUID | None:
    return db_session.scalar(
        select(ChatSession.user_id)
        .where(ChatSession.id == chat_session_id)
        .execution_options(populate_existing=True)
    )


def _triggers_installed(db_session: Session) -> set[str]:
    return set(
        db_session.scalars(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname LIKE 'trg_migrate_no_auth_data%'"
            )
        )
    )


_BOTH_TRIGGERS = {"trg_migrate_no_auth_data", "trg_migrate_no_auth_data_on_upgrade"}
_PLACEHOLDER_ID = UUID(NO_AUTH_PLACEHOLDER_USER_UUID)


def _install_pending_transfer(db_session: Session) -> tuple[ModuleType, UUID]:
    """Simulate an install still waiting for its first registrant, then run
    the fix. Returns the fix module and a legacy chat session id."""
    original = _load(_ORIGINAL_MIGRATION, "no_auth_original_migration")
    fix = _load(_FIX_MIGRATION, "no_auth_standard_only_migration")
    db_session.add(
        User(
            id=_PLACEHOLDER_ID,
            email=NO_AUTH_PLACEHOLDER_USER_EMAIL,
            hashed_password="",
            is_active=False,
        )
    )
    db_session.flush()
    legacy_chat = ChatSession(user_id=_PLACEHOLDER_ID, description="legacy")
    db_session.add(legacy_chat)
    db_session.flush()

    db_session.execute(text(original.MIGRATE_NO_AUTH_TRIGGER_FUNCTION))
    db_session.execute(text(original.MIGRATE_NO_AUTH_TRIGGER))
    with Operations.context(MigrationContext.configure(db_session.connection())):
        fix.upgrade()
    assert _triggers_installed(db_session) == _BOTH_TRIGGERS
    return fix, legacy_chat.id


def _assert_transferred(db_session: Session, chat_id: UUID, owner_id: UUID) -> None:
    assert _owner(db_session, chat_id) == owner_id
    assert db_session.get(User, _PLACEHOLDER_ID, populate_existing=True) is None
    assert _triggers_installed(db_session) == set()


def test_only_standard_user_receives_no_auth_data(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    try:
        fix, chat_id = _install_pending_transfer(db_session)

        _add_user(db_session, AccountType.BOT)
        _add_user(db_session, AccountType.EXT_PERM_USER)
        _add_user(db_session, AccountType.SERVICE_ACCOUNT)
        _add_user(
            db_session,
            AccountType.STANDARD,
            email=get_api_key_fake_email("no-auth", str(uuid4())),
        )
        assert _owner(db_session, chat_id) == _PLACEHOLDER_ID
        assert _triggers_installed(db_session) == _BOTH_TRIGGERS

        registrant = _add_user(db_session, AccountType.STANDARD)
        _assert_transferred(db_session, chat_id, registrant.id)

        # The triggers are gone, so neither direction reinstalls them.
        with Operations.context(MigrationContext.configure(db_session.connection())):
            fix.downgrade()
            fix.upgrade()
        assert _triggers_installed(db_session) == set()
    finally:
        db_session.rollback()


def test_registrant_upgrading_placeholder_row_receives_no_auth_data(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    try:
        _, chat_id = _install_pending_transfer(db_session)
        bot = _add_user(db_session, AccountType.BOT)
        assert _owner(db_session, chat_id) == _PLACEHOLDER_ID

        bot.account_type = AccountType.STANDARD
        db_session.flush()
        _assert_transferred(db_session, chat_id, bot.id)
    finally:
        db_session.rollback()
