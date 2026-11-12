"""The repair task fills the content of plugin versions copied from legacy
skill rows, from their bundles, by the same rules as a save."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.skills import tasks as skill_tasks
from onyx.background.celery.tasks.skills.tasks import (
    repair_backfilled_plugin_versions,
)
from onyx.configs.constants import KV_PLUGIN_VERSION_REPAIR_OVER_LIMITS_KEY
from onyx.db.models import Plugin, PluginSkill, PluginVersion, Skill, User
from onyx.db.plugin import create_skill_plugin__no_commit, legacy_skill_version_content
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.skills import validation
from onyx.skills.content import read_version_contents
from onyx.skills.ingest import delete_bundle_blob, save_skill_bundle_bytes


def _skill_md(name: str) -> str:
    return (
        f"---\nname: {name}\ndescription: Repaired description\n"
        "allowed-tools: Read Grep\n---\n\nRepaired instructions.\n"
    )


def _zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        for path, text in files.items():
            bundle_zip.writestr(path, text)
    return output.getvalue()


@pytest.fixture
def bundle_ids() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    file_store = get_default_file_store()
    for bundle_file_id in ids:
        delete_bundle_blob(file_store, bundle_file_id)


@pytest.fixture(autouse=True)
def _clear_over_limit_versions() -> Iterator[None]:
    yield
    try:
        get_kv_store().delete(KV_PLUGIN_VERSION_REPAIR_OVER_LIMITS_KEY)
    except KvKeyNotFoundError:
        pass


@pytest.fixture
def file_store_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    reads: list[str] = []
    store_type = type(get_default_file_store())
    original = store_type.read_file

    def spy(self: Any, file_id: str, *args: Any, **kwargs: Any) -> Any:
        reads.append(file_id)
        return original(self, file_id, *args, **kwargs)

    monkeypatch.setattr(store_type, "read_file", spy)
    return reads


def _backfilled_skill(
    name: str,
    bundle_bytes: bytes,
    author: User,
    bundle_ids: list[str],
    db_session: Session,
) -> tuple[UUID, str]:
    """A skill whose plugin version 1 was copied from its legacy row, as the
    plugin backfill makes it: a bundle with no file list or SKILL.md text."""
    bundle_file_id = save_skill_bundle_bytes(
        bundle_bytes, display_name=f"{name}.zip", file_store=get_default_file_store()
    )
    bundle_ids.append(bundle_file_id)
    skill = Skill(
        id=uuid4(),
        name=name,
        description="Legacy description",
        bundle_file_id=bundle_file_id,
        bundle_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        author_user_id=author.id,
    )
    db_session.add(skill)
    db_session.flush()
    create_skill_plugin__no_commit(
        skill, legacy_skill_version_content(skill), None, db_session
    )
    db_session.commit()
    version_id = db_session.scalar(
        select(Plugin.current_version_id).where(Plugin.id == skill.id)
    )
    assert version_id is not None
    return version_id, bundle_file_id


def _version(version_id: UUID, db_session: Session) -> PluginVersion:
    db_session.expire_all()
    version = db_session.get(PluginVersion, version_id)
    assert version is not None
    return version


def _root_skill(version_id: UUID, db_session: Session) -> PluginSkill:
    return db_session.scalars(
        select(PluginSkill).where(
            PluginSkill.plugin_version_id == version_id, PluginSkill.path == ""
        )
    ).one()


def test_repair_fills_backfilled_version(
    db_session: Session,
    test_user: User,
    bundle_ids: list[str],
    file_store_reads: list[str],
) -> None:
    name = f"repair-{test_user.id.hex[:8]}"
    skill_md = _skill_md(name)
    files = {"SKILL.md": skill_md, "notes.md": "notes"}
    version_id, bundle_file_id = _backfilled_skill(
        name, _zip(files), test_user, bundle_ids, db_session
    )

    # Before the repair, a reader opens the bundle.
    assert "Repaired instructions." in (
        read_version_contents(version_id, db_session).instructions_markdown
    )
    assert file_store_reads == [bundle_file_id]

    assert repair_backfilled_plugin_versions() >= 1

    version = _version(version_id, db_session)
    expected_manifest = sorted(
        (
            {
                "path": path,
                "size": len(text.encode()),
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
            for path, text in files.items()
        ),
        key=lambda entry: entry["path"],
    )
    assert version.file_manifest == expected_manifest
    assert version.unpacked_size_bytes == sum(len(t.encode()) for t in files.values())
    assert version.file_count == 2
    assert version.is_valid is True
    assert version.bundle_file_id == bundle_file_id
    root = _root_skill(version_id, db_session)
    assert root.skill_md == skill_md
    assert root.frontmatter == {
        "name": name,
        "description": "Repaired description",
        "allowed-tools": "Read Grep",
    }

    file_store_reads.clear()
    read_version_contents(version_id, db_session)
    assert file_store_reads == []


def test_corrupt_bundle_makes_the_version_invalid(
    db_session: Session,
    test_user: User,
    bundle_ids: list[str],
    file_store_reads: list[str],
) -> None:
    version_id, bundle_file_id = _backfilled_skill(
        f"corrupt-{test_user.id.hex[:8]}",
        b"this is not a zip",
        test_user,
        bundle_ids,
        db_session,
    )

    repair_backfilled_plugin_versions()

    version = _version(version_id, db_session)
    assert version.is_valid is False
    assert version.file_manifest is None

    file_store_reads.clear()
    repair_backfilled_plugin_versions()
    assert bundle_file_id not in file_store_reads


def test_bundle_over_a_size_limit_is_tried_again_when_the_limit_rises(
    db_session: Session,
    test_user: User,
    bundle_ids: list[str],
    file_store_reads: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = f"large-{test_user.id.hex[:8]}"
    version_id, bundle_file_id = _backfilled_skill(
        name, _zip({"SKILL.md": _skill_md(name)}), test_user, bundle_ids, db_session
    )

    with monkeypatch.context() as patch:
        patch.setattr(validation, "STORED_ZIP_MAX_BYTES", 10)
        patch.setattr(
            skill_tasks,
            "STORED_BUNDLE_LIMITS",
            [*skill_tasks.STORED_BUNDLE_LIMITS[:2], 10, 1],
        )
        repair_backfilled_plugin_versions()
        version = _version(version_id, db_session)
        assert version.is_valid is None
        assert version.file_manifest is None

        # The same limits do not read the bundle again.
        file_store_reads.clear()
        repair_backfilled_plugin_versions()
        assert bundle_file_id not in file_store_reads

    repair_backfilled_plugin_versions()
    version = _version(version_id, db_session)
    assert version.is_valid is True
    assert version.file_count == 1
    assert _root_skill(version_id, db_session).skill_md == _skill_md(name)
