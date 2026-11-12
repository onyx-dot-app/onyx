import logging
import os
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Protocol
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import create_engine, delete, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import AccountType, LLMModelFlowType, UserFileStatus
from onyx.db.llm import (
    fetch_default_model,
    fetch_existing_llm_provider,
    remove_llm_provider,
    update_default_model,
    upsert_llm_provider,
)
from onyx.db.models import (
    ChatSession,
    MCPServer,
    MCPServer__UserGroup,
    Persona,
    Persona__DocumentSet,
    Persona__PersonaLabel,
    Persona__User,
    Persona__UserGroup,
    Project__UserFile,
    Tool,
    User,
    User__UserGroup,
    UserFile,
    UserProject,
)
from onyx.db.users import assign_user_to_default_groups__no_commit
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.common.models import CI_OPENAI_MODEL
from tests.external_dependency_unit.full_setup import ensure_full_deployment_setup
from tests.external_dependency_unit.session_state_guard import (
    reset_leaked_session_settings,
)

# Opt into the shared @pytest.mark.secrets / test_secrets infrastructure.
from tests.utils.pytest_secrets import (
    pytest_collection_modifyitems as pytest_collection_modifyitems,
)
from tests.utils.pytest_secrets import pytest_configure as pytest_configure
from tests.utils.pytest_secrets import test_secrets as test_secrets


@pytest.fixture
def audit_stream(caplog: pytest.LogCaptureFixture) -> Generator[None, None, None]:
    """``onyx.audit`` sets ``propagate=False``, so caplog's root handler never sees
    its records; hang caplog's handler below that barrier instead. Not autouse — it
    would feed audit records to tests that capture logs for other reasons.
    """
    audit_logger = logging.getLogger("onyx.audit")
    audit_logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        audit_logger.removeHandler(caplog.handler)


@pytest.fixture(autouse=True)
def no_leaked_db_session_settings() -> Generator[None, None, None]:
    """Fail the test that returns a pooled connection with session settings on
    it, instead of a later test that happens to check that connection out."""
    yield
    leaks = reset_leaked_session_settings()
    if leaks:
        pytest.fail(
            "This test left Postgres session settings on pooled connections: "
            f"{leaks}. Use SET LOCAL, reset the setting, or run on the "
            "`isolated_engine` fixture."
        )


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


@pytest.fixture(params=[False, True], ids=["direct", "code_mode"])
def code_mode(request: pytest.FixtureRequest) -> Generator[bool, None, None]:
    """Run the test with CODE_MODE_ENABLED off and on, for chat flows whose
    behavior depends on it. CI runs the rest of this suite with it off."""
    with patch("onyx.chat.execution.CODE_MODE_ENABLED", request.param):
        yield request.param


@pytest.fixture
def isolated_engine(
    db_session: Session,  # noqa: ARG001 - initializes SqlEngine
) -> Generator[Engine, None, None]:
    """An engine with no pool, for tests that change session state (search_path,
    lock_timeout) or hand a connection to migration code. Each connection closes
    when the test returns it, so none of that state reaches the shared app pool."""
    engine = create_engine(SqlEngine.get_engine().url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def full_deployment_setup() -> Generator[None, None, None]:
    """Optional fixture to perform full deployment-like setup on demand.

    Import and call tests.external_dependency_unit.full_setup.ensure_full_deployment_setup
    to initialize Postgres defaults and the document index.
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


def create_processing_user_file(db_session: Session, user_id: UUID) -> UserFile:
    """Insert a UserFile in PROCESSING status and return it."""
    uf = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"test_file_{uuid4().hex[:8]}",
        name=f"test_{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=UserFileStatus.PROCESSING,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def delete_test_user(db_session: Session, *users: User) -> None:
    """Tear down users created by create_test_user. Clears default-group
    membership first — user__user_group.user_id has no ON DELETE CASCADE, so a
    bare delete(user) raises ForeignKeyViolation. Mirrors the production delete
    path in onyx.db.users."""
    _delete_users(db_session, [user.id for user in users])


def _delete_users(db_session: Session, user_ids: Sequence[UUID]) -> None:
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id.in_(user_ids))
    )
    db_session.execute(delete(User).where(User.__table__.c.id.in_(user_ids)))


class MakeTestUser(Protocol):
    def __call__(
        self,
        email_prefix: str,
        account_type: AccountType = AccountType.STANDARD,
        is_admin: bool = False,
    ) -> User: ...


def delete_test_users_and_owned_rows(
    db_session: Session, user_ids: Sequence[UUID], emails: Sequence[str]
) -> None:
    """Delete test-owned chat resources and their non-cascading links."""
    db_session.rollback()
    persona_ids = select(Persona.id).where(Persona.user_id.in_(user_ids))
    persona_id_list = list(db_session.scalars(persona_ids))
    db_session.execute(delete(ChatSession).where(ChatSession.user_id.in_(user_ids)))
    db_session.execute(
        update(ChatSession)
        .where(ChatSession.persona_id.in_(persona_id_list))
        .values(persona_id=None)
    )
    db_session.execute(
        delete(Persona__User).where(
            or_(
                Persona__User.user_id.in_(user_ids),
                Persona__User.persona_id.in_(persona_id_list),
            )
        )
    )
    for association in (
        Persona__DocumentSet,
        Persona__UserGroup,
        Persona__PersonaLabel,
    ):
        db_session.execute(
            delete(association).where(association.persona_id.in_(persona_id_list))
        )
    db_session.execute(delete(Persona).where(Persona.id.in_(persona_id_list)))
    server_ids = select(MCPServer.id).where(MCPServer.owner.in_(emails))
    db_session.execute(
        delete(MCPServer__UserGroup).where(
            MCPServer__UserGroup.mcp_server_id.in_(server_ids)
        )
    )
    db_session.execute(delete(MCPServer).where(MCPServer.owner.in_(emails)))
    db_session.execute(delete(Tool).where(Tool.user_id.in_(user_ids)))
    project_ids = select(UserProject.id).where(UserProject.user_id.in_(user_ids))
    file_ids = select(UserFile.id).where(UserFile.user_id.in_(user_ids))
    db_session.execute(
        update(ChatSession)
        .where(ChatSession.project_id.in_(project_ids))
        .values(project_id=None)
    )
    db_session.execute(
        delete(Project__UserFile).where(
            or_(
                Project__UserFile.project_id.in_(project_ids),
                Project__UserFile.user_file_id.in_(file_ids),
            )
        )
    )
    db_session.execute(delete(UserFile).where(UserFile.user_id.in_(user_ids)))
    db_session.execute(delete(UserProject).where(UserProject.user_id.in_(user_ids)))
    _delete_users(db_session, user_ids)
    db_session.commit()


@pytest.fixture
def make_test_user(db_session: Session) -> Generator[MakeTestUser, None, None]:
    """Create users with `create_test_user`; teardown deletes them and the rows
    they own."""
    created: list[tuple[UUID, str]] = []

    def make(
        email_prefix: str,
        account_type: AccountType = AccountType.STANDARD,
        is_admin: bool = False,
    ) -> User:
        user = create_test_user(db_session, email_prefix, account_type, is_admin)
        created.append((user.id, user.email))
        return user

    try:
        yield make
    finally:
        if created:
            delete_test_users_and_owned_rows(
                db_session,
                [user_id for user_id, _ in created],
                [email for _, email in created],
            )


def ensure_default_llm_provider(db_session: Session, provider_name: str) -> None:
    """Make the test provider's model the default chat model."""
    provider = upsert_llm_provider(
        llm_provider_upsert_request=LLMProviderUpsertRequest(
            name=provider_name,
            provider=LlmProviderNames.OPENAI,
            api_key=os.environ.get("OPENAI_API_KEY", "test"),
            is_public=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=CI_OPENAI_MODEL,
                    is_visible=True,
                )
            ],
            groups=[],
        ),
        db_session=db_session,
    )
    update_default_model(
        db_session, provider.id, CI_OPENAI_MODEL, LLMModelFlowType.CHAT
    )


@contextmanager
def temporary_default_llm_provider(db_session: Session) -> Generator[None, None, None]:
    """Use a private test provider and restore the previous chat default."""
    previous = fetch_default_model(db_session, LLMModelFlowType.CHAT)
    previous_default = (
        None if previous is None else (previous.llm_provider_id, previous.name)
    )
    provider_name = f"test-provider-{uuid4().hex}"
    try:
        ensure_default_llm_provider(db_session, provider_name)
        yield
    finally:
        db_session.rollback()
        if previous_default is not None:
            update_default_model(db_session, *previous_default, LLMModelFlowType.CHAT)
        # Removing the temporary provider also removes its default-flow rows.
        provider = fetch_existing_llm_provider(provider_name, db_session)
        if provider is not None:
            remove_llm_provider(db_session, provider.id)


@pytest.fixture
def default_llm_provider(db_session: Session) -> Generator[None, None, None]:
    with temporary_default_llm_provider(db_session):
        yield


@pytest.fixture(scope="module")
def initialize_file_store() -> Generator[None, None, None]:
    """Initialize the file store for testing.

    Scoped to module level since file store initialization is idempotent
    and doesn't need to be reset between tests.
    """
    get_default_file_store().initialize()
    yield
