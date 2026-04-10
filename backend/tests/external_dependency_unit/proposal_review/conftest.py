"""Shared fixtures for proposal review integration tests.

Uses the same real-PostgreSQL pattern as the parent external_dependency_unit
conftest.  Tables must already exist (via the 61ea78857c97 migration).
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.models import UserRole
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID

# Tables to clean up after each test, in dependency order (children first).
_PROPOSAL_REVIEW_TABLES = [
    "proposal_review_audit_log",
    "proposal_review_decision",
    "proposal_review_proposal_decision",
    "proposal_review_finding",
    "proposal_review_run",
    "proposal_review_document",
    "proposal_review_proposal",
    "proposal_review_rule",
    "proposal_review_ruleset",
    "proposal_review_config",
]


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def db_session(tenant_context: None) -> Generator[Session, None, None]:  # noqa: ARG001
    """Yield a DB session scoped to the current tenant.

    After the test completes, all proposal_review rows are deleted so tests
    don't leave artifacts in the database.
    """
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session

        # Clean up all proposal_review data created during this test
        try:
            for table in _PROPOSAL_REVIEW_TABLES:
                session.execute(text(f"DELETE FROM {table}"))  # noqa: S608
            session.commit()
        except Exception:
            session.rollback()


@pytest.fixture(scope="function")
def test_user(db_session: Session) -> User:
    """Create a throwaway user for FK references (triggered_by, officer_id, etc.)."""
    unique_email = f"pr_test_{uuid4().hex[:8]}@example.com"
    password_helper = PasswordHelper()
    hashed_password = password_helper.hash(password_helper.generate())

    user = User(
        id=uuid4(),
        email=unique_email,
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.ADMIN,
        account_type=AccountType.STANDARD,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
