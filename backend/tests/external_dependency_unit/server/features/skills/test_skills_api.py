"""External-dependency tests for the Skills HTTP surface (spec §7).

We invoke the FastAPI route functions directly with a constructed admin/user
``User`` and the test ``db_session`` — same pattern as the cc-pair sync-attempt
route tests. Pros: no TestClient lifespan, no auth dependency mocking, and we
exercise the real DB + FileStore round-trip.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skills.api import create_custom_skill
from onyx.server.features.skills.api import delete_custom_skill
from onyx.server.features.skills.api import GrantsRequest
from onyx.server.features.skills.api import list_skills_admin
from onyx.server.features.skills.api import list_skills_for_current_user
from onyx.server.features.skills.api import patch_custom_skill
from onyx.server.features.skills.api import PatchSkillRequest
from onyx.server.features.skills.api import replace_custom_skill_bundle
from onyx.server.features.skills.api import replace_custom_skill_grants
from onyx.skills.registry import BuiltinSkillRegistry
from tests.external_dependency_unit.conftest import create_test_user

# ---------------------------------------------------------------------------
# Bundle helpers
# ---------------------------------------------------------------------------


def _build_bundle(entries: list[tuple[str, bytes]] | None = None) -> bytes:
    """Build a minimal valid bundle zip with SKILL.md at root."""
    items = entries or [
        ("SKILL.md", b"# Hello\n\nA test skill.\n"),
        ("scripts/run.sh", b"#!/bin/sh\necho hi\n"),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in items:
            zf.writestr(zipfile.ZipInfo(filename=path), data)
    return buf.getvalue()


def _make_upload(content: bytes, filename: str = "skill.zip") -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content), size=len(content))


def _create(**kwargs: Any) -> Any:
    """Sync wrapper around the async POST handler.

    Lets the synchronous test bodies drive the same route the HTTP layer
    drives, without bringing pytest-asyncio into a test file that otherwise
    has no async needs.
    """
    return asyncio.run(create_custom_skill(**kwargs))


def _replace_bundle(**kwargs: Any) -> Any:
    return asyncio.run(replace_custom_skill_bundle(**kwargs))


def _admin(db_session: Session) -> User:
    return create_test_user(db_session, "admin_skill", role=UserRole.ADMIN)


def _basic_user(db_session: Session) -> User:
    return create_test_user(db_session, "basic_skill", role=UserRole.BASIC)


def _unique_slug(prefix: str) -> str:
    """The shared DB persists between runs, so collide-prone slugs need
    randomization. Mirrors the `create_test_user` pattern for emails.
    """
    return f"{prefix}-{uuid4().hex[:8]}"


def _make_skill(
    db_session: Session,
    *,
    slug: str | None = None,
    name: str = "Test",
    description: str = "Test skill.",
    is_public: bool = True,
    group_ids: list[int] | None = None,
    bundle: bytes | None = None,
    user: User | None = None,
) -> Any:
    """Create a custom skill via the API. Defaults are valid happy-path."""
    return _create(
        bundle=_make_upload(bundle if bundle is not None else _build_bundle()),
        slug=slug if slug is not None else _unique_slug("test"),
        name=name,
        description=description,
        is_public=is_public,
        group_ids=group_ids if group_ids is not None else [],
        user=user if user is not None else _admin(db_session),
        db_session=db_session,
    )


def _build_template_bundle_for_builtin(tmp_path: Path) -> Path:
    """Lay out a built-in skill source dir for registry tests.

    The registry reads frontmatter from SKILL.md (or SKILL.md.template) at
    registration time — these tests need a real on-disk dir.
    """
    source = tmp_path / "builtin-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: Sample Builtin\ndescription: A sample.\n---\n\nbody\n",
        encoding="utf-8",
    )
    return source


@pytest.fixture(autouse=True)
def _reset_registry() -> Any:
    """Each test starts with a clean registry singleton.

    Other tests in this session may have registered built-ins; resetting
    keeps `list_skills_admin` results deterministic without polluting them.
    """
    BuiltinSkillRegistry._reset_for_testing()
    yield
    BuiltinSkillRegistry._reset_for_testing()


# Most tests require Postgres + FileStore + the dynamic test schema.
pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")


# ---------------------------------------------------------------------------
# P2.032 — POST /custom: happy + each invalid bundle path
# ---------------------------------------------------------------------------


def test_create_custom_skill_happy_path(db_session: Session) -> None:
    bundle = _build_bundle()
    slug = _unique_slug("hello")

    result = _make_skill(db_session, slug=slug, bundle=bundle)

    assert result.slug == slug
    assert result.is_public is True
    assert result.bundle_sha256
    assert result.bundle_size_bytes == len(bundle)
    # Row + blob actually exist
    row = db_session.scalars(select(Skill).where(Skill.id == result.id)).one()
    assert row.bundle_file_id
    assert get_default_file_store().get_file_size(row.bundle_file_id) == len(bundle)


@pytest.mark.parametrize(
    "bad_bundle, slug, exc_match",
    [
        (b"not a zip", "ok-slug", "valid zip"),
        # Missing SKILL.md at root
        (
            _build_bundle([("docs/README.md", b"hi")]),
            "missing-skillmd",
            "SKILL.md missing",
        ),
    ],
)
def test_create_custom_skill_invalid_bundle_rejected(
    db_session: Session, bad_bundle: bytes, slug: str, exc_match: str
) -> None:
    pre_count = db_session.scalar(select(func.count(Skill.id))) or 0

    with pytest.raises(OnyxError, match=exc_match):
        _make_skill(db_session, slug=slug, bundle=bad_bundle, name="Bad")

    post_count = db_session.scalar(select(func.count(Skill.id))) or 0
    assert post_count == pre_count


# ---------------------------------------------------------------------------
# P2.033 — replace bundle: old blob deleted after commit
# ---------------------------------------------------------------------------


def test_replace_bundle_deletes_old_blob(db_session: Session) -> None:
    first = _make_skill(db_session, slug=_unique_slug("rotate"))
    row = db_session.scalars(select(Skill).where(Skill.id == first.id)).one()
    old_blob_id = row.bundle_file_id

    new_bundle = _build_bundle([("SKILL.md", b"# Hello v2\n"), ("notes.md", b"v2\n")])
    updated = _replace_bundle(
        skill_id=first.id,
        bundle=_make_upload(new_bundle, "v2.zip"),
        db_session=db_session,
    )

    assert updated.bundle_sha256 != first.bundle_sha256
    assert updated.bundle_size_bytes == len(new_bundle)
    # Old blob is gone
    file_store = get_default_file_store()
    assert file_store.get_file_size(old_blob_id) is None


# ---------------------------------------------------------------------------
# P2.034 — grants visibility via GET /skills
# ---------------------------------------------------------------------------


def _put_user_in_group(db_session: Session, user: User, group: UserGroup) -> None:
    db_session.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
    db_session.commit()


def test_grants_visible_only_to_members(db_session: Session) -> None:
    admin = _admin(db_session)
    member = _basic_user(db_session)
    outsider = _basic_user(db_session)

    group = UserGroup(name=f"skills-grp-{uuid4().hex[:8]}")
    db_session.add(group)
    db_session.commit()
    _put_user_in_group(db_session, member, group)

    slug = _unique_slug("restricted")
    created = _make_skill(
        db_session,
        slug=slug,
        name="Restricted",
        description="Only group sees this",
        is_public=False,
        user=admin,
    )

    replace_custom_skill_grants(
        skill_id=created.id,
        payload=GrantsRequest(group_ids=[group.id]),
        db_session=db_session,
    )

    member_view = list_skills_for_current_user(user=member, db_session=db_session)
    outsider_view = list_skills_for_current_user(user=outsider, db_session=db_session)

    member_slugs = {s.slug for s in member_view.custom}
    outsider_slugs = {s.slug for s in outsider_view.custom}
    assert slug in member_slugs
    assert slug not in outsider_slugs


# ---------------------------------------------------------------------------
# P2.035 — PATCH slug rename re-checks uniqueness
# ---------------------------------------------------------------------------


def test_patch_slug_rejects_collision(db_session: Session) -> None:
    slug_a = _unique_slug("alpha")
    slug_b = _unique_slug("beta")
    a = _make_skill(db_session, slug=slug_a)
    b = _make_skill(db_session, slug=slug_b)

    with pytest.raises(OnyxError, match="already exists"):
        patch_custom_skill(
            skill_id=b.id,
            payload=PatchSkillRequest(slug=slug_a),
            db_session=db_session,
        )

    # And the renamed-to-a-fresh-slug case still works
    renamed_slug = _unique_slug("beta-renamed")
    renamed = patch_custom_skill(
        skill_id=b.id,
        payload=PatchSkillRequest(slug=renamed_slug),
        db_session=db_session,
    )
    assert renamed.slug == renamed_slug
    # First skill untouched
    a_row = db_session.scalars(select(Skill).where(Skill.id == a.id)).one()
    assert a_row.slug == slug_a


# ---------------------------------------------------------------------------
# P2.036 — GET /admin/skills reports unavailable built-ins with reason
# ---------------------------------------------------------------------------


def test_admin_list_surfaces_unavailable_builtin(
    db_session: Session, tmp_path: Path
) -> None:
    source_dir = _build_template_bundle_for_builtin(tmp_path)
    registry = BuiltinSkillRegistry.instance()
    registry.register(
        "image-generation",
        source_dir,
        is_available=lambda _db: False,
        unavailable_reason="No image-generation provider configured.",
    )
    registry.register("pptx", source_dir)  # always-available baseline

    result = list_skills_admin(db_session=db_session)

    by_slug = {b.slug: b for b in result.builtin}
    assert by_slug["pptx"].available is True
    assert by_slug["pptx"].unavailable_reason is None

    unavail = by_slug["image-generation"]
    assert unavail.available is False
    assert unavail.unavailable_reason is not None
    assert "image-generation provider" in unavail.unavailable_reason


# ---------------------------------------------------------------------------
# DELETE smoke — row + blob removed
# ---------------------------------------------------------------------------


def test_delete_removes_row_and_blob(db_session: Session) -> None:
    created = _make_skill(db_session, slug=_unique_slug("to-delete"))
    row = db_session.scalars(select(Skill).where(Skill.id == created.id)).one()
    blob_id = row.bundle_file_id

    delete_custom_skill(skill_id=created.id, db_session=db_session)

    assert (
        db_session.scalars(select(Skill).where(Skill.id == created.id)).one_or_none()
        is None
    )
    assert get_default_file_store().get_file_size(blob_id) is None


# ---------------------------------------------------------------------------
# Reserved-slug check via PATCH (mirrors create-side check)
# ---------------------------------------------------------------------------


def test_patch_rejects_reserved_slug(db_session: Session, tmp_path: Path) -> None:
    registry = BuiltinSkillRegistry.instance()
    registry.register("pptx", _build_template_bundle_for_builtin(tmp_path))

    skill = _make_skill(db_session, slug=_unique_slug("renamable"))

    with pytest.raises(OnyxError, match="reserved"):
        patch_custom_skill(
            skill_id=skill.id,
            payload=PatchSkillRequest(slug="pptx"),
            db_session=db_session,
        )


# ---------------------------------------------------------------------------
# Grant request idempotency (replace semantics)
# ---------------------------------------------------------------------------


def test_replace_grants_is_full_replace(db_session: Session) -> None:
    g1 = UserGroup(name=f"g1-{uuid4().hex[:8]}")
    g2 = UserGroup(name=f"g2-{uuid4().hex[:8]}")
    db_session.add_all([g1, g2])
    db_session.commit()

    created = _make_skill(db_session, slug=_unique_slug("grants-flip"), is_public=False)

    replace_custom_skill_grants(
        skill_id=created.id,
        payload=GrantsRequest(group_ids=[g1.id, g2.id]),
        db_session=db_session,
    )
    assert _grant_ids(db_session, created.id) == sorted([g1.id, g2.id])

    replace_custom_skill_grants(
        skill_id=created.id,
        payload=GrantsRequest(group_ids=[g2.id]),
        db_session=db_session,
    )
    assert _grant_ids(db_session, created.id) == [g2.id]


def _grant_ids(db_session: Session, skill_id: Any) -> list[int]:
    rows = db_session.scalars(
        select(Skill__UserGroup.user_group_id).where(
            Skill__UserGroup.skill_id == skill_id
        )
    ).all()
    return sorted(int(r) for r in rows)
