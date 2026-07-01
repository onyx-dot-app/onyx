"""Fixtures for build mode tests."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SkillSharePermission
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.constants import LlmProviderNames
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.common.craft.skill_table_isolation import restore_skill_tables
from tests.common.craft.skill_table_isolation import snapshot_skill_tables
from tests.common.craft.stubs import StubSandboxManager


def _best_effort_delete(model: type[Any], ids: Iterable[Any]) -> None:
    ids = [i for i in ids if i is not None]
    if not ids:
        return
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        try:
            with get_session_with_current_tenant() as session:
                session.execute(text("SET lock_timeout = '10s'"))
                for row_id in ids:
                    row = session.get(model, row_id)
                    if row is not None:
                        session.delete(row)
                session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_skill_tables(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Snapshot the committed skill tables before each test, restore after."""
    snapshot = snapshot_skill_tables(db_session)
    yield
    db_session.rollback()
    restore_skill_tables(db_session, snapshot)


@pytest.fixture(scope="module", autouse=True)
def _seed_default_llm_provider() -> Generator[None, None, None]:
    """Seed a default LLM provider (no-op if one exists); fake key, never invoked."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    seeded_name: str | None = None
    try:
        with get_session_with_current_tenant() as session:
            if fetch_default_llm_model(session) is None:
                seeded_name = f"craft-ci-default-{uuid4().hex[:8]}"
                provider = upsert_llm_provider(
                    LLMProviderUpsertRequest(
                        name=seeded_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key="sk-craft-ci-not-used",
                        api_key_changed=True,
                        model_configurations=[
                            ModelConfigurationUpsertRequest(
                                name="gpt-5-mini", is_visible=True
                            )
                        ],
                    ),
                    db_session=session,
                )
                update_default_provider(
                    provider_id=provider.id,
                    model_name="gpt-5-mini",
                    db_session=session,
                )
                session.commit()
        yield
    finally:
        if seeded_name is not None:
            with get_session_with_current_tenant() as session:
                existing = fetch_existing_llm_provider(
                    name=seeded_name, db_session=session
                )
                if existing is not None:
                    remove_llm_provider(session, existing.id)
                    session.commit()
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def test_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[User, None, None]:
    password_helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"build_test_{uuid4().hex[:8]}@example.com",
        hashed_password=password_helper.hash(password_helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.EXT_PERM_USER,
        account_type=AccountType.EXT_PERM_USER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    # Release uncommitted locks before the separate-session delete cascades from this user.
    db_session.rollback()
    _best_effort_delete(User, [user.id])


@pytest.fixture(scope="function")
def build_session(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
) -> BuildSession:
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


@pytest.fixture(scope="function")
def sandbox(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., Sandbox]:
    """Factory: create a ``Sandbox`` row for a user (default owner test_user, status RUNNING)."""

    def _make(
        user: User | None = None,
        status: SandboxStatus = SandboxStatus.RUNNING,
    ) -> Sandbox:
        owner = user or test_user
        row = create_sandbox__no_commit(db_session=db_session, user_id=owner.id)
        if status != SandboxStatus.PROVISIONING:
            update_sandbox_status__no_commit(db_session, row.id, status)
        db_session.commit()
        db_session.refresh(row)
        return row

    return _make


@pytest.fixture(scope="function")
def build_session_with_user(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., BuildSession]:
    """Factory: create a ``BuildSession`` tied to a user (and optional sandbox)."""

    def _make(
        user: User | None = None,
        status: BuildSessionStatus = BuildSessionStatus.ACTIVE,
        provision_sandbox: bool = False,
        name: str | None = None,
    ) -> BuildSession:
        owner = user or test_user
        if provision_sandbox:
            sandbox(user=owner)
        session_row = BuildSession(
            id=uuid4(),
            user_id=owner.id,
            name=name or "Test Build Session",
            status=status,
        )
        db_session.add(session_row)
        db_session.commit()
        db_session.refresh(session_row)
        return session_row

    return _make


def _build_zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(path, data)
    return buf.getvalue()


@pytest.fixture(scope="function")
def seeded_skill(
    db_session: Session,
    request: pytest.FixtureRequest,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., Skill]:
    """Factory: create a ``Skill`` row + its bundle in the file store."""
    file_store = get_default_file_store()
    file_store.initialize()
    bundle_file_ids: list[str] = []

    def _cleanup() -> None:
        for file_id in bundle_file_ids:
            try:
                file_store.delete_file(file_id, error_on_missing=False)
            except Exception:
                pass

    request.addfinalizer(_cleanup)

    def _make(
        slug: str,
        public: bool = False,
        groups: Iterable[UserGroup] | None = None,
        bundle_files: dict[str, bytes | str] | None = None,
        author_user_id: UUID | None = None,
    ) -> Skill:
        if bundle_files is None:
            bundle_files = {
                "SKILL.md": (
                    f"---\nname: {slug}\ndescription: Seeded skill {slug}\n---\n"
                ),
            }
        bundle_bytes = _build_zip(bundle_files)
        bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()

        bundle_file_id = file_store.save_file(
            content=io.BytesIO(bundle_bytes),
            display_name=f"{slug}.zip",
            file_origin=FileOrigin.SKILL_BUNDLE,
            file_type="application/zip",
        )
        bundle_file_ids.append(bundle_file_id)

        skill = Skill(
            id=uuid4(),
            slug=slug,
            name=slug,
            description=f"Seeded skill {slug}",
            bundle_file_id=bundle_file_id,
            bundle_sha256=bundle_sha256,
            public_permission=SkillSharePermission.VIEWER if public else None,
            enabled=True,
            author_user_id=author_user_id,
        )
        db_session.add(skill)
        db_session.commit()
        db_session.refresh(skill)

        for group in groups or []:
            db_session.add(Skill__UserGroup(skill_id=skill.id, user_group_id=group.id))
        db_session.commit()
        return skill

    return _make


@pytest.fixture(scope="function")
def stub_sandbox_manager() -> StubSandboxManager:
    return StubSandboxManager()


@pytest.fixture(scope="function")
def failing_sandbox_manager() -> Callable[..., StubSandboxManager]:
    """Factory: a stub pre-configured with a ``fail_on`` failure-injection map."""

    def _make(
        fail_on: dict[UUID, Exception] | None = None,
    ) -> StubSandboxManager:
        stub = StubSandboxManager()
        if fail_on is not None:
            stub.write_files_to_sandbox_raises_for = dict(fail_on)
        return stub

    return _make


@pytest.fixture(scope="function")
def session_manager_with_stub(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> SessionManager:
    """``SessionManager`` bound to the stub sandbox backend (patches both lookup sites)."""
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: stub_sandbox_manager,
    )
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.factory._sandbox_manager_instance",
        stub_sandbox_manager,
    )
    sm = SessionManager(db_session)
    assert sm._sandbox_manager is stub_sandbox_manager
    return sm
