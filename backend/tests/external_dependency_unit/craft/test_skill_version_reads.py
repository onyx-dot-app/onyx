"""Readers take the bundle and content of the plugin version each user runs.

Owners and share recipients run the current version. Users who see a plugin
only through the organization run the published version. The editor, the
preview and the skill list read version content from the database, and open
the bundle only for a version copied from a legacy skill row.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import Plugin, PluginVersion, Skill, User
from onyx.db.skill import (
    SkillSharingChange,
    create_custom_skill__no_commit,
    replace_skill_bundle,
    replace_skill_shares,
    set_skill_installation_policy,
)
from onyx.db.users import delete_user_from_db__no_commit
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.api import (
    fetch_custom_skill_for_edit,
    list_skills_for_current_user,
    preview_skill_for_current_user,
)
from onyx.skills.ingest import delete_bundle_blob, ingest_skill_bundle
from onyx.skills.push import build_skills_fileset_for_user, push_skills_for_users
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user


def _bundle(name: str, version: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Skill {version}\n---\n\n"
            f"Instructions {version}\n",
        )
        bundle_zip.writestr("notes.md", f"notes {version}")
    return output.getvalue()


@dataclass
class _PublishedSkill:
    skill: Skill
    author: User
    recipient: User
    org_only: User
    first_version_id: UUID
    current_version_id: UUID


@pytest.fixture
def bundle_ids() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    file_store = get_default_file_store()
    for bundle_file_id in ids:
        delete_bundle_blob(file_store, bundle_file_id)


@pytest.fixture(scope="module")
def created_user_ids() -> Iterator[list[UUID]]:
    """Users the module made. They go after the last test, once the skill
    table restore has removed the plugins that their marketplaces hold."""
    ids: list[UUID] = []
    yield ids
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        for user_id in ids:
            user = session.get(User, user_id)
            if user is not None:
                delete_user_from_db__no_commit(user, session)
        session.commit()


@pytest.fixture
def new_user(db_session: Session, created_user_ids: list[UUID]) -> Callable[[], User]:
    def _make() -> User:
        user = make_user(db_session, standard_account=True)
        created_user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def file_store_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record each file store read, and still serve it."""
    reads: list[str] = []
    store_type = type(get_default_file_store())
    original = store_type.read_file

    def spy(self: Any, file_id: str, *args: Any, **kwargs: Any) -> Any:
        reads.append(file_id)
        return original(self, file_id, *args, **kwargs)

    monkeypatch.setattr(store_type, "read_file", spy)
    return reads


def _current_version_id(skill_id: UUID, db_session: Session) -> UUID:
    version_id = db_session.scalar(
        select(Plugin.current_version_id).where(Plugin.id == skill_id)
    )
    assert version_id is not None
    return version_id


@pytest.fixture
def published_skill(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    bundle_ids: list[str],
    new_user: Callable[[], User],
) -> _PublishedSkill:
    """A published skill at version 2 whose organization still runs version 1,
    as after a save before "Publish update" exists. Installed by default, so
    every user who sees it runs it."""
    author = new_user()
    recipient = new_user()
    org_only = new_user()
    name = f"versioned-{author.id.hex[:8]}"
    file_store = get_default_file_store()

    first = ingest_skill_bundle(
        _bundle(name, "one"), f"{name}.zip", file_store, expected_name=name
    )
    bundle_ids.append(first.bundle_file_id)
    skill, _ = create_custom_skill__no_commit(
        first,
        author,
        db_session,
        change=SkillSharingChange(
            public_permission=SkillSharePermission.VIEWER,
            set_public_permission=True,
        ),
    )
    first_version_id = _current_version_id(skill.id, db_session)
    set_skill_installation_policy(skill, SkillInstallationPolicy.DEFAULT, db_session)
    replace_skill_shares(
        skill=skill,
        db_session=db_session,
        user_shares={recipient.id: SkillSharePermission.VIEWER},
    )

    second = ingest_skill_bundle(
        _bundle(name, "two"), f"{name}.zip", file_store, expected_name=name
    )
    bundle_ids.append(second.bundle_file_id)
    replace_skill_bundle(
        skill=skill,
        ingested=second,
        base_version_id=None,
        user=author,
        skip_if_unchanged=False,
        db_session=db_session,
    )
    plugin = db_session.get(Plugin, skill.id)
    assert plugin is not None
    current_version_id = plugin.current_version_id
    plugin.published_version_id = first_version_id
    db_session.commit()
    return _PublishedSkill(
        skill=skill,
        author=author,
        recipient=recipient,
        org_only=org_only,
        first_version_id=first_version_id,
        current_version_id=current_version_id,
    )


def _notes(files: dict[str, bytes], name: str) -> bytes:
    return files[f"{name}/notes.md"]


def test_org_only_user_runs_published_version_and_recipient_runs_current(
    published_skill: _PublishedSkill, db_session: Session
) -> None:
    name = published_skill.skill.name

    org_files = build_skills_fileset_for_user(published_skill.org_only, db_session)
    recipient_files = build_skills_fileset_for_user(
        published_skill.recipient, db_session
    )
    author_files = build_skills_fileset_for_user(published_skill.author, db_session)

    assert _notes(org_files, name) == b"notes one"
    assert b"Instructions one" in org_files[f"{name}/SKILL.md"]
    assert _notes(recipient_files, name) == b"notes two"
    assert _notes(author_files, name) == b"notes two"

    org_preview = preview_skill_for_current_user(
        published_skill.skill.id, user=published_skill.org_only, db_session=db_session
    )
    recipient_preview = preview_skill_for_current_user(
        published_skill.skill.id,
        user=published_skill.recipient,
        db_session=db_session,
    )
    assert org_preview.instructions_markdown == "Instructions one"
    assert recipient_preview.instructions_markdown == "Instructions two"


class _RecordingSandboxManager:
    """Records each push call; a push call sends one sandbox."""

    def __init__(self) -> None:
        self.pushes: list[dict[UUID, dict[str, bytes]]] = []

    def push_to_sandbox(
        self, *, sandbox_id: UUID, mount_path: str, files: dict[str, bytes]
    ) -> SimpleNamespace:
        del mount_path
        self.pushes.append({sandbox_id: files})
        return SimpleNamespace(targets=1, succeeded=1, failures=[])


def test_push_sends_each_user_the_version_they_run(
    published_skill: _PublishedSkill,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_sandbox = make_sandbox(db_session, published_skill.org_only)
    recipient_sandbox = make_sandbox(db_session, published_skill.recipient)
    db_session.commit()
    manager = _RecordingSandboxManager()
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: manager)
    name = published_skill.skill.name
    users = {published_skill.org_only.id, published_skill.recipient.id}

    push_skills_for_users(users, db_session)
    db_session.commit()

    first_push = {
        sandbox_id: files
        for push_call in manager.pushes
        for sandbox_id, files in push_call.items()
    }
    assert len(manager.pushes) == 2
    assert _notes(first_push[org_sandbox.id], name) == b"notes one"
    assert _notes(first_push[recipient_sandbox.id], name) == b"notes two"

    # Publishing the update changes only what organization users run, so only
    # their sandbox gets a new hash and a new push.
    plugin = db_session.get(Plugin, published_skill.skill.id)
    assert plugin is not None
    plugin.published_version_id = published_skill.current_version_id
    db_session.commit()
    push_skills_for_users(users, db_session)
    db_session.commit()

    second_push = manager.pushes[2]
    assert len(manager.pushes) == 3
    assert set(second_push) == {org_sandbox.id}
    assert _notes(second_push[org_sandbox.id], name) == b"notes two"


def test_editor_and_preview_make_no_file_store_read_for_stored_content(
    published_skill: _PublishedSkill,
    db_session: Session,
    file_store_reads: list[str],
) -> None:
    edit = fetch_custom_skill_for_edit(
        published_skill.skill.id, user=published_skill.author, db_session=db_session
    )
    preview = preview_skill_for_current_user(
        published_skill.skill.id, user=published_skill.author, db_session=db_session
    )

    assert file_store_reads == []
    assert edit.instructions_markdown == "Instructions two"
    assert [(entry.path, entry.size) for entry in edit.files] == [
        ("notes.md", len(b"notes two"))
    ]
    assert edit.current_version_id == published_skill.current_version_id
    assert preview.instructions_markdown == "Instructions two"


def test_editor_and_preview_open_the_bundle_of_a_backfilled_version(
    seeded_skill: Callable[..., Skill],
    db_session: Session,
    file_store_reads: list[str],
    new_user: Callable[[], User],
) -> None:
    author = new_user()
    db_session.commit()
    skill = seeded_skill(
        f"backfilled-{author.id.hex[:8]}",
        author_user_id=author.id,
        bundle_files={
            "SKILL.md": (
                f"---\nname: backfilled-{author.id.hex[:8]}\n"
                "description: Backfilled\n---\n\nFrom the bundle\n"
            ),
            "refs/a.md": "a",
        },
    )
    version = db_session.scalar(
        select(PluginVersion).where(
            PluginVersion.id == _current_version_id(skill.id, db_session)
        )
    )
    assert version is not None and version.file_manifest is None

    edit = fetch_custom_skill_for_edit(skill.id, user=author, db_session=db_session)
    preview = preview_skill_for_current_user(
        skill.id, user=author, db_session=db_session
    )

    assert file_store_reads == [version.bundle_file_id, version.bundle_file_id]
    assert edit.instructions_markdown == "From the bundle"
    assert [entry.path for entry in edit.files] == ["refs/a.md"]
    assert preview.instructions_markdown == "From the bundle"


def test_backfilled_version_lists_name_and_description_without_file_store_read(
    seeded_skill: Callable[..., Skill],
    db_session: Session,
    file_store_reads: list[str],
    new_user: Callable[[], User],
) -> None:
    viewer = new_user()
    db_session.commit()
    skill = seeded_skill(f"listed-{viewer.id.hex[:8]}", public=True)

    listed = list_skills_for_current_user(user=viewer, db_session=db_session)

    [row] = [row for row in listed.customs if row.id == skill.id]
    assert row.name == skill.name
    assert row.description == f"Seeded skill {skill.name}"
    assert file_store_reads == []


def test_file_store_spy_records_reads(file_store_reads: list[str]) -> None:
    """The no-read tests depend on this spy seeing every read."""
    with pytest.raises(FileRecordNotFoundError):
        get_default_file_store().read_file("does-not-exist")
    assert file_store_reads == ["does-not-exist"]
