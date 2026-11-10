from __future__ import annotations

import io
import zipfile
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Skill, User, UserSkillPreference
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.api import import_github_skills
from onyx.server.features.skill.models import GitHubSkillsImportRequest
from onyx.skills.bundle import build_skill_md
from onyx.skills.models import GitHubRepository, GitHubSkillBundle
from tests.external_dependency_unit.conftest import MakeTestUser
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


def _delete_bundles(db_session: Session, name: str) -> list[Skill]:
    """Drop the stored blobs of every skill with this name; returns the rows."""
    rows = list(db_session.scalars(select(Skill).where(Skill.name == name)))
    file_store = get_default_file_store()
    for row in rows:
        if (
            row.current_version is not None
            and row.current_version.bundle_file_id is not None
        ):
            file_store.delete_file(
                row.current_version.bundle_file_id, error_on_missing=False
            )
    return rows


def test_import_refuses_existing_library_name_without_blocking_others(
    db_session: Session,
    standard_user: User,
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
        author_user_id=standard_user.id,
    )
    db_session.add(
        UserSkillPreference(
            user_id=standard_user.id,
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
        "onyx.server.features.skill.api.github_authorization_header",
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
        user=standard_user,
        db_session=db_session,
        http_request=Request({"type": "http"}),
    )

    imported_by_name = {result.skill.name: result for result in response.imported}
    assert set(imported_by_name) == {unique_name}
    assert imported_by_name[unique_name].skill.enabled is True
    assert imported_by_name[unique_name].disabled_reason is None
    assert {item.name: item.reason for item in response.not_imported} == {
        "pptx": "A built-in Onyx skill already uses this name.",
        conflict_name: (
            f"A live skill named '{conflict_name}' already exists in this library. "
            "Upload a new version instead."
        ),
    }
    assert db_session.scalars(
        select(Skill.id).where(Skill.name == conflict_name)
    ).all() == [existing.id]
    assert pushed_user_ids == [{standard_user.id}]

    created_ids = [result.skill.id for result in response.imported]
    created_rows = list(
        db_session.scalars(select(Skill).where(Skill.id.in_(created_ids)))
    )
    enabled_names = set(
        db_session.scalars(
            select(UserSkillPreference.name).where(
                UserSkillPreference.user_id == standard_user.id
            )
        )
    )
    assert enabled_names == {conflict_name, unique_name}
    assert all(row.author_user_id == standard_user.id for row in created_rows)

    file_store = get_default_file_store()
    for row in created_rows:
        if (
            row.current_version is not None
            and row.current_version.bundle_file_id is not None
        ):
            file_store.delete_file(
                row.current_version.bundle_file_id, error_on_missing=False
            )


def test_import_creates_only_first_new_skill_with_each_library_name(
    db_session: Session,
    standard_user: User,
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
        "onyx.server.features.skill.api.github_authorization_header",
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
        user=standard_user,
        db_session=db_session,
        http_request=Request({"type": "http"}),
    )

    assert [result.skill.enabled for result in response.imported] == [True]
    assert response.imported[0].disabled_reason is None
    assert [(item.path, item.reason) for item in response.not_imported] == [
        (
            f"second/{name}",
            f"A live skill named '{name}' already exists in this library. Upload a new version instead.",
        )
    ]
    assert db_session.scalars(select(Skill.id).where(Skill.name == name)).all() == [
        response.imported[0].skill.id
    ]

    file_store = get_default_file_store()
    for result in response.imported:
        row = db_session.get(Skill, result.skill.id)
        if (
            row is not None
            and row.current_version is not None
            and row.current_version.bundle_file_id is not None
        ):
            file_store.delete_file(
                row.current_version.bundle_file_id, error_on_missing=False
            )


def test_import_applies_shared_access_before_publication(
    db_session: Session,
    make_test_user: MakeTestUser,
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db.enums import SkillSharePermission
    from onyx.server.features.skill.models import SkillShareRequest

    name = f"shared-import-{uuid4().hex[:8]}"
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda *_args, **_kwargs: (
            GitHubRepository(owner="owner", repo="repository", revision=_REVISION),
            [
                GitHubSkillBundle(
                    path=name, name=name, description=name, bundle_bytes=_bundle(name)
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.github_authorization_header",
        lambda *_args: None,
    )
    published: list[SkillSharePermission | None] = []

    def record_publication(_user_ids: set[UUID], session: Session) -> None:
        skill = session.scalar(select(Skill).where(Skill.name == name))
        published.append(skill.public_permission if skill else None)

    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users", record_publication
    )
    request = GitHubSkillsImportRequest(
        repository="owner/repository",
        revision=_REVISION,
        paths=[name],
        sharing=SkillShareRequest(public_permission=SkillSharePermission.VIEWER),
    )
    # Company access needs global manage-skills; only the Admin group grants it.
    basic_user = make_test_user("import-basic")
    admin = make_test_user("import-admin", is_admin=True)
    try:
        denied = import_github_skills(
            request,
            user=basic_user,
            db_session=db_session,
            http_request=Request({"type": "http"}),
        )
        assert denied.imported == []
        assert [item.reason for item in denied.not_imported] == [
            "Company access changes require global manage-skills permission."
        ]
        assert published == []

        result = import_github_skills(
            request,
            user=admin,
            db_session=db_session,
            http_request=Request({"type": "http"}),
        )
        assert result.not_imported == []
        assert len(result.imported) == 1
        assert published == [SkillSharePermission.VIEWER]
    finally:
        for row in _delete_bundles(db_session, name):
            db_session.delete(row)
        db_session.commit()


def test_import_with_policy_keeps_first_skill_when_a_name_repeats(
    db_session: Session,
    make_test_user: MakeTestUser,
    initialize_file_store: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.db.enums import SkillInstallationPolicy
    from onyx.server.features.skill.models import SkillShareRequest

    name = f"policy-dup-{uuid4().hex[:8]}"
    paths = [f"first/{name}", f"second/{name}"]
    monkeypatch.setattr(
        "onyx.server.features.skill.api.fetch_github_skill_bundles",
        lambda *_args, **_kwargs: (
            GitHubRepository(owner="owner", repo="repository", revision=_REVISION),
            [
                GitHubSkillBundle(
                    path=path, name=name, description=path, bundle_bytes=_bundle(name)
                )
                for path in paths
            ],
        ),
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.github_authorization_header",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "onyx.server.features.skill.api.push_skills_for_users", lambda *_args: None
    )
    # Installation policy needs global manage-skills; only the Admin group grants it.
    admin = make_test_user("import-policy-admin", is_admin=True)

    response = import_github_skills(
        GitHubSkillsImportRequest(
            repository="owner/repository",
            revision=_REVISION,
            paths=paths,
            sharing=SkillShareRequest(
                installation_policy=SkillInstallationPolicy.DEFAULT
            ),
        ),
        user=admin,
        db_session=db_session,
        http_request=Request({"type": "http"}),
    )

    try:
        assert [result.skill.name for result in response.imported] == [name]
        assert response.imported[0].skill.installation_policy == (
            SkillInstallationPolicy.DEFAULT
        )
        assert [item.path for item in response.not_imported] == [paths[1]]
        assert len(_delete_bundles(db_session, name)) == 1
    finally:
        for row in _delete_bundles(db_session, name):
            db_session.delete(row)
        db_session.commit()
