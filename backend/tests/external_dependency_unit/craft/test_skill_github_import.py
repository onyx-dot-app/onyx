from __future__ import annotations

import io
import zipfile
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Skill, User, UserSkillPreference
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.api import import_github_skills
from onyx.server.features.skill.models import GitHubSkillsImportRequest
from onyx.skills.bundle import build_skill_md
from onyx.skills.models import GitHubRepository, GitHubSkillBundle
from tests.external_dependency_unit.craft.db_helpers import make_skill

_REVISION = "a" * 40


def _bundle(name: str) -> bytes:
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
        bundle.writestr("references/guide.md", f"Supporting content for {name}")
    return output.getvalue()


def test_import_creates_conflicting_skills_disabled_without_blocking_others(
    db_session: Session,
    test_user: User,
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:8]
    conflict_name = f"conflict-{suffix}"
    unique_name = f"unique-{suffix}"
    existing = make_skill(
        db_session,
        name=conflict_name,
        author_user_id=test_user.id,
    )
    db_session.add(
        UserSkillPreference(
            user_id=test_user.id,
            skill_id=existing.id,
            name=existing.name,
        )
    )
    db_session.commit()
    discovered = [
        GitHubSkillBundle(
            path=f"skills/{conflict_name}",
            name=conflict_name,
            description="Conflicting skill",
            bundle_bytes=_bundle(conflict_name),
        ),
        GitHubSkillBundle(
            path=f"skills/{unique_name}",
            name=unique_name,
            description="Unique skill",
            bundle_bytes=_bundle(unique_name),
        ),
        GitHubSkillBundle(
            path="skills/pptx",
            name="pptx",
            description="Presentations",
            bundle_bytes=None,
            unavailable_reason="A built-in Onyx skill already uses this name.",
        ),
    ]
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda *_args, **_kwargs: (
            GitHubRepository(
                owner="owner",
                repo="repository",
                revision=_REVISION,
            ),
            discovered,
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api._github_authorization_header",
        lambda *_args: None,
    )
    pushed_user_ids: list[set[UUID]] = []
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users",
        lambda user_ids, _db: pushed_user_ids.append(user_ids),
    )

    response = import_github_skills(
        GitHubSkillsImportRequest(
            repository="owner/repository",
            revision=_REVISION,
            paths=[
                f"skills/{conflict_name}",
                f"skills/{unique_name}",
                "skills/pptx",
            ],
        ),
        user=test_user,
        db_session=db_session,
    )

    imported_by_name = {result.skill.name: result for result in response.imported}
    assert imported_by_name[conflict_name].enabled is False
    assert "already enabled" in (imported_by_name[conflict_name].disabled_reason or "")
    assert imported_by_name[unique_name].enabled is True
    assert imported_by_name[unique_name].disabled_reason is None
    assert [(item.name, item.reason) for item in response.not_imported] == [
        ("pptx", "A built-in Onyx skill already uses this name.")
    ]
    assert pushed_user_ids == [{test_user.id}]

    created_ids = [result.skill.id for result in response.imported]
    created_rows = list(
        db_session.scalars(select(Skill).where(Skill.id.in_(created_ids)))
    )
    enabled_names = set(
        db_session.scalars(
            select(UserSkillPreference.name).where(
                UserSkillPreference.user_id == test_user.id
            )
        )
    )
    assert enabled_names == {conflict_name, unique_name}
    assert all(row.author_user_id == test_user.id for row in created_rows)

    file_store = get_default_file_store()
    for row in created_rows:
        if row.bundle_file_id is not None:
            file_store.delete_file(row.bundle_file_id, error_on_missing=False)


def test_import_enables_only_first_new_skill_with_each_name(
    db_session: Session,
    test_user: User,
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = f"duplicate-{uuid4().hex[:8]}"
    discovered = [
        GitHubSkillBundle(
            path=f"first/{name}",
            name=name,
            description="First copy",
            bundle_bytes=_bundle(name),
        ),
        GitHubSkillBundle(
            path=f"second/{name}",
            name=name,
            description="Second copy",
            bundle_bytes=_bundle(name),
        ),
    ]
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda *_args, **_kwargs: (
            GitHubRepository(
                owner="owner",
                repo="repository",
                revision=_REVISION,
            ),
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
            repository="owner/repository",
            revision=_REVISION,
            paths=[f"first/{name}", f"second/{name}"],
        ),
        user=test_user,
        db_session=db_session,
    )

    assert [result.enabled for result in response.imported] == [True, False]
    assert response.imported[1].disabled_reason is not None
    assert response.not_imported == []

    file_store = get_default_file_store()
    for result in response.imported:
        row = db_session.get(Skill, result.skill.id)
        if row is not None and row.bundle_file_id is not None:
            file_store.delete_file(row.bundle_file_id, error_on_missing=False)
