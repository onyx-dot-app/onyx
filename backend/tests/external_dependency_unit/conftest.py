from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.models import User, User__UserGroup
from onyx.db.users import assign_user_to_default_groups__no_commit
from onyx.file_store.file_store import get_default_file_store
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.full_setup import ensure_full_deployment_setup

# Opt into the shared @pytest.mark.secrets / test_secrets infrastructure.
from tests.utils.pytest_secrets import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)
from tests.utils.pytest_secrets import pytest_configure as pytest_configure
from tests.utils.pytest_secrets import test_secrets as test_secrets


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a database session for testing using the actual PostgreSQL database"""
    # Make sure that the db engine is initialized before any tests are run
    SqlEngine.init_engine(
        pool_size=10,
        max_overflow=5,
    )
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="session")
def full_deployment_setup() -> Generator[None, None, None]:
    """Optional fixture to perform full deployment-like setup on demand.

    Import and call tests.external_dependency_unit.startup.full_setup.ensure_full_deployment_setup
    to initialize Postgres defaults, Vespa indices, and seed initial docs.
    """
    ensure_full_deployment_setup()
    yield


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    """Set up tenant context for testing"""
    # Set the tenant context for the test
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        # Reset the tenant context after the test
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def create_test_user(
    db_session: Session,
    email_prefix: str,
    account_type: AccountType = AccountType.STANDARD,
    is_admin: bool = False,
    assign_default_group: bool = True,
) -> User:
    """Create a test user. Assigns the seeded Basic
    (or Admin if is_admin=True) default group and populates
    effective_permissions; skipped for BOT/EXT_PERM_USER/ANONYMOUS.

    Pass assign_default_group=False for the group-less case — a service account
    in no group is what the old LIMITED role described."""
    unique_email = f"{email_prefix}_{uuid4().hex[:8]}@example.com"

    password_helper = PasswordHelper()
    password = password_helper.generate()
    hashed_password = password_helper.hash(password)

    user = User(
        id=uuid4(),
        email=unique_email,
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        account_type=account_type,
    )
    db_session.add(user)
    db_session.flush()

    if assign_default_group:
        assign_user_to_default_groups__no_commit(db_session, user, is_admin=is_admin)

    db_session.commit()
    db_session.refresh(user)
    return user


def delete_test_user(db_session: Session, *users: User) -> None:
    """Tear down users created by create_test_user. Clears default-group
    membership first — user__user_group.user_id has no ON DELETE CASCADE, so a
    bare delete(user) raises ForeignKeyViolation. Mirrors the production delete
    path in onyx.db.users."""
    user_ids = [user.id for user in users]
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id.in_(user_ids))
    )
    db_session.execute(delete(User).where(User.__table__.c.id.in_(user_ids)))


@pytest.fixture(scope="module")
def initialize_file_store() -> Generator[None, None, None]:
    """Initialize the file store for testing.

    Scoped to module level since file store initialization is idempotent
    and doesn't need to be reset between tests.
    """
    get_default_file_store().initialize()
    yield
