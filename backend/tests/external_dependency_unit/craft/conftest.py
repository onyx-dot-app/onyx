"""Fixtures for build mode tests."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import BuildSessionStatus
from onyx.db.models import BuildSession
from onyx.db.models import User
from onyx.db.models import UserRole
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a database session for testing using the actual PostgreSQL database."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    """Set up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def test_user(db_session: Session, tenant_context: None) -> User:  # noqa: ARG001
    """Create a test user for build session tests."""
    unique_email = f"build_test_{uuid4().hex[:8]}@example.com"

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
        role=UserRole.EXT_PERM_USER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def build_session(
    db_session: Session, test_user: User, tenant_context: None  # noqa: ARG001
) -> BuildSession:
    """Create a test build session."""
    session = BuildSession(
        id=uuid4(),
        user_id=test_user.id,
        name="Test Build Session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session
