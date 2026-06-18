"""External-dependency tests for create_custom_external_app_from_repo.

Requires: Postgres, MinIO/S3.
Run via:
  uv run python -m dotenv -f .vscode/.env run -- pytest \
    backend/tests/external_dependency_unit/build/test_external_app_from_repo.py -q
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

import onyx.server.features.build.external_apps.api as api
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.external_apps.models import (
    CreateCustomExternalAppFromRepoRequest,
)
from onyx.skills.bundle import validate_custom_bundle
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID

_UPSTREAM = ["https://api.example.com/*"]
_AUTH_TEMPLATE: dict[str, str] = {"Authorization": "Bearer {api_key}"}
_ORG_CREDENTIALS: dict[str, str] = {"api_key": "sk-test"}


def _make_tar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            b = data.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            ti.mtime = 0
            tf.addfile(ti, io.BytesIO(b))
    return buf.getvalue()


def _skill_md(name: str = "My Skill", description: str = "does things") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n# body\n"


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def test_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[User, None, None]:
    helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"repo_app_test_{uuid4().hex[:8]}@example.com",
        hashed_password=helper.hash(helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.ADMIN,
        account_type=AccountType.STANDARD,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    db_session.rollback()
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
        try:
            with get_session_with_current_tenant() as s:
                row = s.get(User, user.id)
                if row is not None:
                    s.delete(row)
                    s.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


@pytest.fixture(scope="module", autouse=True)
def initialize_file_store() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        get_default_file_store().initialize()
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateCustomExternalAppFromRepo:
    def test_happy_path_creates_app_and_skill(
        self,
        db_session: Session,
        test_user: User,
        tenant_context: None,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slug = f"repo-skill-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("Repo Skill", "from repo")}
        )
        monkeypatch.setattr(api, "fetch_repo_archive", lambda _parsed: archive)
        monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)

        body = CreateCustomExternalAppFromRepoRequest(
            name="My Repo App",
            description="",
            upstream_url_patterns=_UPSTREAM,
            auth_template=_AUTH_TEMPLATE,
            organization_credentials=_ORG_CREDENTIALS,
            enabled=True,
            source="owner/repo",
            slug=slug,
        )
        resp = api.create_custom_external_app_from_repo(
            body=body,
            _=test_user,
            db_session=db_session,
        )

        assert resp.app_type == ExternalAppType.CUSTOM
        assert resp.name == "My Repo App"
        # blank description falls back to SKILL.md description
        assert resp.description == "from repo"
        assert resp.upstream_url_patterns == _UPSTREAM
        assert resp.auth_template == _AUTH_TEMPLATE

        skill = db_session.scalar(select(Skill).where(Skill.slug == slug))
        assert skill is not None
        assert skill.bundle_file_id  # bundle was stored

        app = db_session.scalar(
            select(ExternalApp).where(ExternalApp.skill_id == skill.id)
        )
        assert app is not None
        assert app.app_type == ExternalAppType.CUSTOM

        # verify stored bundle passes validation
        file_store = get_default_file_store()
        blob = b"".join(file_store.read_file(skill.bundle_file_id, use_tempfile=False))
        validate_custom_bundle(blob, slug=slug)

        db_session.execute(delete(Skill).where(Skill.slug == slug))
        db_session.commit()

    def test_nonexistent_slug_raises_not_found(
        self,
        db_session: Session,
        test_user: User,
        tenant_context: None,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        present_slug = f"present-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{present_slug}/SKILL.md": _skill_md("Present", "here")}
        )
        monkeypatch.setattr(api, "fetch_repo_archive", lambda _parsed: archive)
        monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)

        body = CreateCustomExternalAppFromRepoRequest(
            name="Missing",
            description="",
            upstream_url_patterns=_UPSTREAM,
            auth_template={},
            organization_credentials={},
            enabled=True,
            source="owner/repo",
            slug="does-not-exist",
        )
        with pytest.raises(OnyxError) as exc_info:
            api.create_custom_external_app_from_repo(
                body=body,
                _=test_user,
                db_session=db_session,
            )

        err = exc_info.value
        assert err.error_code == OnyxErrorCode.NOT_FOUND

        # no orphan rows
        assert (
            db_session.scalar(select(Skill).where(Skill.slug == "does-not-exist"))
            is None
        )

    def test_upstream_url_patterns_and_auth_template_persisted(
        self,
        db_session: Session,
        test_user: User,
        tenant_context: None,  # noqa: ARG002
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slug = f"persist-test-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("Persist", "p")}
        )
        monkeypatch.setattr(api, "fetch_repo_archive", lambda _parsed: archive)
        monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)

        auth = {"X-Api-Key": "{token}"}
        org_creds: dict[str, str] = {"token": "secret-abc"}
        patterns = ["https://service.example.com/api/*"]

        body = CreateCustomExternalAppFromRepoRequest(
            name="Persist App",
            description="",
            upstream_url_patterns=patterns,
            auth_template=auth,
            organization_credentials=org_creds,
            enabled=True,
            source="owner/repo",
            slug=slug,
        )
        resp = api.create_custom_external_app_from_repo(
            body=body,
            _=test_user,
            db_session=db_session,
        )

        assert resp.upstream_url_patterns == patterns
        assert resp.auth_template == auth

        skill = db_session.scalar(select(Skill).where(Skill.slug == slug))
        assert skill is not None
        app = db_session.scalar(
            select(ExternalApp).where(ExternalApp.skill_id == skill.id)
        )
        assert app is not None
        assert list(app.upstream_url_patterns) == patterns
        assert app.auth_template == auth
        assert app.organization_credentials.get_value(apply_mask=False) == org_creds

        db_session.execute(delete(Skill).where(Skill.slug == slug))
        db_session.commit()
