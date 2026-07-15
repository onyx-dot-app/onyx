from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.api import import_github_skills
from onyx.server.features.skill.models import GitHubSkillsImportRequest
from onyx.skills.bundle import build_skill_md
from onyx.skills.bundle import inspect_custom_bundle
from onyx.skills.bundle import slug_from_skill_name
from onyx.skills.models import GitHubRepository
from onyx.skills.models import GitHubSkillBundle
from tests.external_dependency_unit.craft.db_helpers import make_skill

_REVISION = "a" * 40


def _bundle(name: str, supporting_path: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "SKILL.md",
            build_skill_md(
                name=name,
                description=f"Description for {name}",
                instructions_markdown=f"Use {name} carefully.",
            ),
        )
        bundle.writestr(supporting_path, f"Supporting content for {name}")
    return output.getvalue()


def test_import_github_skills_creates_personal_skills_with_supporting_files(
    db_session: Session,
    test_user: User,
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:8]
    names = [f"GitHub Alpha {suffix}", f"GitHub Beta {suffix}"]
    discovered = [
        GitHubSkillBundle(
            path="skills/alpha",
            slug=slug_from_skill_name(names[0]),
            name=names[0],
            description=f"Description for {names[0]}",
            bundle_bytes=_bundle(names[0], "references/alpha.md"),
        ),
        GitHubSkillBundle(
            path="skills/beta",
            slug=slug_from_skill_name(names[1]),
            name=names[1],
            description=f"Description for {names[1]}",
            bundle_bytes=_bundle(names[1], "scripts/beta.py"),
        ),
    ]
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda _source, _authorization, **_kwargs: (
            GitHubRepository(owner="owner", repo="repo", ref=_REVISION),
            discovered,
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api._github_authorization_header",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users",
        lambda *_args: None,
    )

    response = import_github_skills(
        GitHubSkillsImportRequest(
            repository="owner/repo",
            revision=_REVISION,
            paths=["skills/alpha", "skills/beta"],
        ),
        user=test_user,
        db_session=db_session,
    )

    rows = db_session.scalars(
        select(Skill).where(Skill.slug.in_([skill.slug for skill in discovered]))
    ).all()
    file_store = get_default_file_store()
    try:
        assert {skill.slug for skill in response} == {
            skill.slug for skill in discovered
        }
        assert len(rows) == 2
        assert all(row.author_user_id == test_user.id for row in rows)
        assert all(row.public_permission is None for row in rows)

        stored_files = []
        for row in rows:
            assert row.bundle_file_id is not None
            stored_bundle = b"".join(
                file_store.read_file(row.bundle_file_id, use_tempfile=False)
            )
            stored_files.append(
                {file.path for file in inspect_custom_bundle(stored_bundle).files}
            )
        assert {"references/alpha.md"} in stored_files
        assert {"scripts/beta.py"} in stored_files
    finally:
        for row in rows:
            if row.bundle_file_id is not None:
                file_store.delete_file(row.bundle_file_id, error_on_missing=False)


def test_import_github_skills_rolls_back_the_batch_on_a_slug_collision(
    db_session: Session,
    test_user: User,
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:8]
    new_name = f"GitHub New {suffix}"
    collision_name = f"GitHub Existing {suffix}"
    collision_slug = slug_from_skill_name(collision_name)
    make_skill(db_session, slug=collision_slug)
    db_session.commit()
    discovered = [
        GitHubSkillBundle(
            path="skills/new",
            slug=slug_from_skill_name(new_name),
            name=new_name,
            description="New skill",
            bundle_bytes=_bundle(new_name, "new.txt"),
        ),
        GitHubSkillBundle(
            path="skills/existing",
            slug=collision_slug,
            name=collision_name,
            description="Existing skill",
            bundle_bytes=_bundle(collision_name, "existing.txt"),
        ),
    ]
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda _source, _authorization, **_kwargs: (
            GitHubRepository(owner="owner", repo="repo", ref=_REVISION),
            discovered,
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api._github_authorization_header",
        lambda *_args: None,
    )

    with pytest.raises(OnyxError, match="already exists") as exc_info:
        import_github_skills(
            GitHubSkillsImportRequest(
                repository="owner/repo",
                revision=_REVISION,
                paths=["skills/new", "skills/existing"],
            ),
            user=test_user,
            db_session=db_session,
        )

    assert collision_name in exc_info.value.detail
    assert "Rename it in SKILL.md, then try again." in exc_info.value.detail
    db_session.rollback()
    assert (
        db_session.scalar(
            select(Skill).where(Skill.slug == slug_from_skill_name(new_name))
        )
        is None
    )


def test_import_github_skills_rejects_an_unavailable_selected_path(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable_reason = "Can't import: 'pptx' is a reserved skill name in Onyx."
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda _source, _authorization, **_kwargs: (
            GitHubRepository(owner="anthropics", repo="skills", ref=_REVISION),
            [
                GitHubSkillBundle(
                    path="skills/pptx",
                    slug="pptx",
                    name="pptx",
                    description="Create and edit presentations",
                    bundle_bytes=None,
                    unavailable_reason=unavailable_reason,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api._github_authorization_header",
        lambda *_args: None,
    )

    with pytest.raises(OnyxError, match="reserved in Onyx") as exc_info:
        import_github_skills(
            GitHubSkillsImportRequest(
                repository="anthropics/skills",
                revision=_REVISION,
                paths=["skills/pptx"],
            ),
            user=test_user,
            db_session=db_session,
        )

    assert exc_info.value.detail == unavailable_reason
