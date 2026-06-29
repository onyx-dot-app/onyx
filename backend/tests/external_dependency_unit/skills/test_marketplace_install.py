"""External-dependency tests for _install_personal_repo_skills.

Requires: Postgres, Redis, MinIO/S3 (real db_session + file store).
Run via: uv run python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit/skills/test_marketplace_install.py -x -q
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.db.skill import get_group_ids_for_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.api import _install_admin_repo_skills
from onyx.server.features.skill.api import _install_personal_repo_skills
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import validate_custom_bundle
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_VALID_SKILL_MD = "---\nname: My Skill\ndescription: does things\n---\n# body\n"


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


def _init_engine() -> None:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)


def _make_user(db_session: Session) -> User:
    helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"marketplace_test_{uuid4().hex[:8]}@example.com",
        hashed_password=helper.hash(helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.BASIC,
        account_type=AccountType.STANDARD,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_admin_user(db_session: Session) -> User:
    helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"marketplace_admin_{uuid4().hex[:8]}@example.com",
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
    return user


def _make_group(db_session: Session) -> UserGroup:
    group = UserGroup(
        name=f"test-group-{uuid4().hex[:8]}",
        is_up_to_date=True,
        is_up_for_deletion=False,
        is_default=False,
    )
    db_session.add(group)
    db_session.commit()
    db_session.refresh(group)
    return group


def _delete_group(group_id: int) -> None:
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        try:
            with get_session_with_current_tenant() as session:
                row = session.get(UserGroup, group_id)
                if row is not None:
                    session.delete(row)
                    session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


def _delete_user(user_id: object) -> None:
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        try:
            with get_session_with_current_tenant() as session:
                row = session.get(User, user_id)
                if row is not None:
                    session.delete(row)
                    session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


def _delete_skills_by_slugs(slugs: list[str]) -> None:
    if not slugs:
        return
    try:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
        try:
            with get_session_with_current_tenant() as session:
                rows = (
                    session.execute(select(Skill).where(Skill.slug.in_(slugs)))
                    .scalars()
                    .all()
                )
                file_store = get_default_file_store()
                for row in rows:
                    if row.bundle_file_id:
                        try:
                            file_store.delete_file(
                                row.bundle_file_id, error_on_missing=False
                            )
                        except Exception:
                            pass
                    session.delete(row)
                session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        pass


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    _init_engine()
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
    user = _make_user(db_session)
    yield user
    db_session.rollback()
    _delete_user(user.id)


@pytest.fixture(scope="module", autouse=True)
def initialize_file_store() -> Generator[None, None, None]:
    _init_engine()
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        get_default_file_store().initialize()
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


class TestInstallPersonalRepoSkills:
    def test_happy_path_two_skills(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        slug_a = f"skill-alpha-{uuid4().hex[:6]}"
        slug_b = f"skill-beta-{uuid4().hex[:6]}"
        archive = _make_tar(
            {
                f"repo-main/skills/{slug_a}/SKILL.md": _skill_md("Alpha", "alpha desc"),
                f"repo-main/skills/{slug_b}/SKILL.md": _skill_md("Beta", "beta desc"),
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _source: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug_a, slug_b]))

        result = _install_personal_repo_skills(
            "owner/repo", [slug_a, slug_b], test_user, db_session
        )

        assert len(result.created) == 2
        assert result.failures == []
        created_slugs = {r.slug for r in result.created}
        assert slug_a in created_slugs
        assert slug_b in created_slugs

        # Rows persist in DB with a bundle_file_id
        rows = (
            db_session.execute(select(Skill).where(Skill.slug.in_([slug_a, slug_b])))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        for row in rows:
            assert row.bundle_file_id is not None

    def test_happy_path_bundle_passes_validate(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        slug = f"validate-skill-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("Validate", "desc")}
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _source: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug]))

        result = _install_personal_repo_skills(
            "owner/repo", [slug], test_user, db_session
        )
        assert len(result.created) == 1

        row = db_session.execute(select(Skill).where(Skill.slug == slug)).scalar_one()
        assert row.bundle_file_id is not None

        file_store = get_default_file_store()
        blob = b"".join(file_store.read_file(row.bundle_file_id, use_tempfile=False))
        validate_custom_bundle(blob, slug=slug)

    def test_slug_collision_is_per_skill_failure(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        existing_slug = f"existing-{uuid4().hex[:6]}"
        new_slug = f"newskill-{uuid4().hex[:6]}"
        archive = _make_tar(
            {
                f"repo-main/skills/{existing_slug}/SKILL.md": _skill_md(
                    "Existing", "e"
                ),
                f"repo-main/skills/{new_slug}/SKILL.md": _skill_md("New", "n"),
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _source: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([existing_slug, new_slug]))

        # First install to create the collision candidate
        result1 = _install_personal_repo_skills(
            "owner/repo", [existing_slug], test_user, db_session
        )
        assert len(result1.created) == 1
        assert result1.failures == []

        # Second install: same slug (collision) + new slug
        result2 = _install_personal_repo_skills(
            "owner/repo", [existing_slug, new_slug], test_user, db_session
        )
        assert len(result2.created) == 1
        assert result2.created[0].slug == new_slug
        assert len(result2.failures) == 1
        assert result2.failures[0].slug == existing_slug

    def test_cap_enforcement_raises(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        slug_a = f"cap-skill-a-{uuid4().hex[:6]}"
        slug_b = f"cap-skill-b-{uuid4().hex[:6]}"
        archive = _make_tar(
            {
                f"repo-main/skills/{slug_a}/SKILL.md": _skill_md("CapA", "a"),
                f"repo-main/skills/{slug_b}/SKILL.md": _skill_md("CapB", "b"),
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _source: archive,
        )
        # Cap at 1 so installing 2 skills exceeds the limit.
        monkeypatch.setattr(
            "onyx.server.features.skill.api.MAX_PERSONAL_SKILLS_PER_USER", 1
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug_a, slug_b]))

        with pytest.raises(OnyxError):
            _install_personal_repo_skills(
                "owner/repo", [slug_a, slug_b], test_user, db_session
            )

    def test_slug_not_in_repo_is_failure_entry(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        real_slug = f"real-skill-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{real_slug}/SKILL.md": _skill_md("Real", "r")}
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _source: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([real_slug]))

        missing_slug = f"does-not-exist-{uuid4().hex[:6]}"
        result = _install_personal_repo_skills(
            "owner/repo", [missing_slug], test_user, db_session
        )

        assert result.created == []
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.slug == missing_slug
        assert "not found" in failure.error.lower()


class TestInstallAdminRepoSkills:
    def test_public_no_groups(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Admin install with is_public=True and no group_ids → skill is public."""
        admin = _make_admin_user(db_session)
        request.addfinalizer(lambda: _delete_user(admin.id))

        slug = f"admin-pub-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("AdminPub", "admin pub")}
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug]))

        result = _install_admin_repo_skills(
            "owner/repo",
            [slug],
            is_public=True,
            group_ids=[],
            user=admin,
            db_session=db_session,
        )

        assert len(result.created) == 1
        assert result.failures == []

        row = db_session.execute(select(Skill).where(Skill.slug == slug)).scalar_one()
        assert row.is_public is True
        assert get_group_ids_for_skill(row.id, db_session) == []

    def test_public_with_group(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Admin install with is_public=True and a group_id → group grant exists."""
        admin = _make_admin_user(db_session)
        group = _make_group(db_session)
        request.addfinalizer(lambda: _delete_user(admin.id))
        request.addfinalizer(lambda: _delete_group(group.id))

        slug = f"admin-grp-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("AdminGrp", "grp")}
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug]))

        result = _install_admin_repo_skills(
            "owner/repo",
            [slug],
            is_public=True,
            group_ids=[group.id],
            user=admin,
            db_session=db_session,
        )

        assert len(result.created) == 1
        row = db_session.execute(select(Skill).where(Skill.slug == slug)).scalar_one()
        assert row.is_public is True
        assert group.id in get_group_ids_for_skill(row.id, db_session)

    def test_admin_install_exceeds_personal_cap(
        self,
        db_session: Session,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Admin path has no personal-skill cap — installing > MAX succeeds."""
        admin = _make_admin_user(db_session)
        request.addfinalizer(lambda: _delete_user(admin.id))

        slugs = [f"admin-cap-{uuid4().hex[:6]}" for _ in range(3)]
        archive = _make_tar(
            {
                f"repo-main/skills/{s}/SKILL.md": _skill_md(s.capitalize(), "x")
                for s in slugs
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )
        # Cap personal skills at 1 — admin path must not be gated by this.
        monkeypatch.setattr(
            "onyx.server.features.skill.api.MAX_PERSONAL_SKILLS_PER_USER", 1
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs(slugs))

        result = _install_admin_repo_skills(
            "owner/repo",
            slugs,
            is_public=True,
            group_ids=[],
            user=admin,
            db_session=db_session,
        )

        assert len(result.created) == 3
        assert result.failures == []


class TestReservedSlugRejection:
    def test_reserved_slug_is_failure_normal_slug_is_created(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A skill whose slug matches a built-in ends up in failures; others are created."""
        # Pick a known built-in slug from the registry.
        reserved_slug = next(iter(BUILT_IN_SKILLS))
        normal_slug = f"normal-skill-{uuid4().hex[:6]}"

        archive = _make_tar(
            {
                f"repo-main/skills/{reserved_slug}/SKILL.md": _skill_md(
                    "Reserved", "reserved"
                ),
                f"repo-main/skills/{normal_slug}/SKILL.md": _skill_md("Normal", "n"),
            }
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([normal_slug]))

        result = _install_personal_repo_skills(
            "owner/repo",
            [reserved_slug, normal_slug],
            test_user,
            db_session,
        )

        assert len(result.created) == 1
        assert result.created[0].slug == normal_slug

        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.slug == reserved_slug
        assert "reserved" in failure.error.lower()


class TestBlobCleanupOnFailure:
    def test_create_skill_failure_cleans_blob(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """When create_skill__no_commit raises OnyxError, the uploaded blob is deleted."""
        slug = f"fail-skill-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("Fail", "f")}
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )

        deleted_blob_ids: list[str] = []

        real_delete = __import__(
            "onyx.skills.ingest", fromlist=["delete_bundle_blob"]
        ).delete_bundle_blob

        def _spy_delete(file_store: object, file_id: str) -> None:
            deleted_blob_ids.append(file_id)
            real_delete(file_store, file_id)

        monkeypatch.setattr(
            "onyx.server.features.skill.api.delete_bundle_blob",
            _spy_delete,
        )

        def _raising_create(**_kwargs: object) -> None:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "boom")

        monkeypatch.setattr(
            "onyx.server.features.skill.api.create_skill__no_commit",
            _raising_create,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug]))

        result = _install_personal_repo_skills(
            "owner/repo", [slug], test_user, db_session
        )

        assert result.created == []
        assert len(result.failures) == 1
        assert result.failures[0].slug == slug
        # blob must have been cleaned up
        assert len(deleted_blob_ids) == 1

        # No orphaned Skill row
        row = db_session.execute(
            select(Skill).where(Skill.slug == slug)
        ).scalar_one_or_none()
        assert row is None

    def test_non_onyx_error_records_internal_error(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Non-OnyxError from create_skill__no_commit → failure entry with 'internal error'."""
        slug = f"internal-err-{uuid4().hex[:6]}"
        archive = _make_tar(
            {f"repo-main/skills/{slug}/SKILL.md": _skill_md("Internal", "i")}
        )
        monkeypatch.setattr(
            "onyx.server.features.skill.api.fetch_repo_archive",
            lambda _parsed: archive,
        )

        def _runtime_raise(**_kwargs: object) -> None:
            raise RuntimeError("unexpected")

        monkeypatch.setattr(
            "onyx.server.features.skill.api.create_skill__no_commit",
            _runtime_raise,
        )
        request.addfinalizer(lambda: _delete_skills_by_slugs([slug]))

        result = _install_personal_repo_skills(
            "owner/repo", [slug], test_user, db_session
        )

        assert result.created == []
        assert len(result.failures) == 1
        assert result.failures[0].error == "internal error"
