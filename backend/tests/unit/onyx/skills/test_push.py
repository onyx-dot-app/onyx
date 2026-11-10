from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Skill, SkillVersion, User
from onyx.file_store.file_store import FileStore
from onyx.skills import push


def _bundle(name: str, *, wrapper: str | None = None) -> bytes:
    output = io.BytesIO()
    prefix = f"{wrapper}/" if wrapper is not None else ""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle_zip:
        bundle_zip.writestr(
            f"{prefix}SKILL.md",
            (
                f"---\nname: {name}\ndescription: Description\n"
                "license: Apache-2.0\nx-custom: retained\n---\n\nBody\n"
            ),
        )
        bundle_zip.writestr(f"{prefix}scripts/run.py", b"print('hello')\n")
    return output.getvalue()


def _skill(
    *,
    name: str = "canonical-name",
    is_valid: bool | None = None,
) -> Skill:
    version = SkillVersion(id=uuid4(), bundle_file_id="bundle-id", is_valid=is_valid)
    return Skill(
        id=uuid4(),
        name=name,
        built_in_skill_id=None,
        current_version_id=version.id,
        current_version=version,
    )


def test_skill_runtime_hash_covers_files_and_connectable_apps() -> None:
    files = {"b/SKILL.md": b"second", "a/SKILL.md": b"first"}

    assert push.compute_skill_runtime_hash(
        files, "apps"
    ) == push.compute_skill_runtime_hash(dict(reversed(files.items())), "apps")
    assert push.compute_skill_runtime_hash(
        files, "apps"
    ) != push.compute_skill_runtime_hash({**files, "a/SKILL.md": b"changed"}, "apps")
    assert push.compute_skill_runtime_hash(
        files, "apps"
    ) != push.compute_skill_runtime_hash(files, "different apps")


def test_assemble_keeps_first_resolved_name(monkeypatch: pytest.MonkeyPatch) -> None:
    user = cast(User, SimpleNamespace())
    skills = [_skill(is_valid=True), _skill(is_valid=True)]

    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(_bundle("canonical-name"))
    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())
    files = push._assemble_fileset(skills, user, MagicMock(spec=Session))
    assert "canonical-name/SKILL.md" in files
    assert file_store.read_file.call_count == 1


def test_assemble_classifies_and_hydrates_valid_unclassified_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(_bundle("canonical-name"))
    persist = MagicMock()
    skill = _skill()
    user = cast(User, SimpleNamespace())

    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", persist)

    files = push._assemble_fileset([skill], user, MagicMock(spec=Session))

    assert files["canonical-name/scripts/run.py"] == b"print('hello')\n"
    assert b"license: Apache-2.0" in files["canonical-name/SKILL.md"]
    assert b"x-custom: retained" in files["canonical-name/SKILL.md"]
    assert skill.current_version is not None
    assert skill.current_version.is_valid is None
    persist.assert_called_once_with(
        [
            push.SkillValidityUpdate(
                skill_id=skill.id,
                version_id=skill.current_version.id,
                bundle_file_id="bundle-id",
                is_valid=True,
            )
        ]
    )


def test_assemble_marks_invalid_legacy_name_and_does_not_hydrate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(_bundle("Legacy Display Name"))
    persist = MagicMock()
    skill = _skill()
    user = cast(User, SimpleNamespace())

    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", persist)

    files = push._assemble_fileset([skill], user, MagicMock(spec=Session))

    assert files == {}
    assert skill.current_version is not None
    assert skill.current_version.is_valid is None
    persist.assert_called_once_with(
        [
            push.SkillValidityUpdate(
                skill_id=skill.id,
                version_id=skill.current_version.id,
                bundle_file_id="bundle-id",
                is_valid=False,
            )
        ]
    )


def test_assemble_leaves_transient_read_failure_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.side_effect = TimeoutError("temporary outage")
    persist = MagicMock()
    skill = _skill()
    user = cast(User, SimpleNamespace())

    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", persist)

    files = push._assemble_fileset([skill], user, MagicMock(spec=Session))

    assert files == {}
    persist.assert_called_once_with([])


def test_assemble_skips_known_invalid_skill_without_reading_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    persist = MagicMock()
    skill = _skill(is_valid=False)
    user = cast(User, SimpleNamespace())

    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", persist)

    files = push._assemble_fileset([skill], user, MagicMock(spec=Session))

    assert files == {}
    file_store.read_file.assert_not_called()
    persist.assert_called_once_with([])


def test_assemble_normalizes_wrapped_known_valid_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(
        _bundle("canonical-name", wrapper="canonical-name")
    )
    persist = MagicMock()
    validate = MagicMock()
    skill = _skill(is_valid=True)
    user = cast(User, SimpleNamespace())

    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", persist)
    monkeypatch.setattr(push, "validate_stored_custom_skill", validate)

    files = push._assemble_fileset([skill], user, MagicMock(spec=Session))

    assert files["canonical-name/SKILL.md"].startswith(b"---\n")
    assert files["canonical-name/scripts/run.py"] == b"print('hello')\n"
    assert "canonical-name/canonical-name/SKILL.md" not in files
    persist.assert_called_once_with([])
    validate.assert_not_called()


def test_assemble_resolves_skill_dir_only_in_root_skill_md(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            "---\nname: canonical-name\ndescription: d\n---\n"
            "Run ${CLAUDE_SKILL_DIR}/scripts/x.py\n",
        )
        bundle_zip.writestr("scripts/x.py", "print('${CLAUDE_SKILL_DIR}')\n")
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(output.getvalue())
    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())

    files = push._assemble_fileset(
        [_skill(is_valid=True)], cast(User, SimpleNamespace()), MagicMock(spec=Session)
    )

    assert files["canonical-name/SKILL.md"].endswith(
        b"Run /workspace/managed/skills/canonical-name/scripts/x.py\n"
    )
    assert files["canonical-name/scripts/x.py"] == b"print('${CLAUDE_SKILL_DIR}')\n"


def test_assemble_hydrates_when_validity_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(_bundle("canonical-name"))
    skill = _skill()
    user = cast(User, SimpleNamespace())

    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(
        push,
        "persist_skill_validity",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )

    files = push._assemble_fileset([skill], user, MagicMock(spec=Session))

    assert files["canonical-name/SKILL.md"].startswith(b"---\n")


def test_user_payload_returns_hydrated_files_and_connectable_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_skill = _skill(is_valid=True)
    invalid_skill = _skill(name="invalid-skill", is_valid=False)
    user = cast(User, SimpleNamespace())
    db_session = MagicMock(spec=Session)
    list_runtime_skills = MagicMock(return_value=[valid_skill, invalid_skill])
    assemble_fileset = MagicMock(return_value={"canonical-name/SKILL.md": b"content"})
    monkeypatch.setattr(
        push,
        "list_runtime_skills_for_user",
        list_runtime_skills,
    )
    monkeypatch.setattr(
        push,
        "_assemble_fileset",
        assemble_fileset,
    )
    monkeypatch.setattr(push, "get_connectable_apps_for_user", lambda *_args: [])
    monkeypatch.setattr(push, "build_connectable_apps_list", lambda _apps: "apps")

    apps_section, files = push.build_user_skills_payload(user, db_session)

    assert apps_section == "apps"
    assert files == {"canonical-name/SKILL.md": b"content"}
    list_runtime_skills.assert_called_once_with(
        user=user,
        db_session=db_session,
    )
    assemble_fileset.assert_called_once_with(
        [valid_skill, invalid_skill],
        user,
        db_session,
    )


def test_assemble_skips_oversized_expansion_and_keeps_other_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md",
            "---\nname: canonical-name\ndescription: d\n---\n"
            + "${CLAUDE_SKILL_DIR}/scripts/x.py\n" * 30,
        )
        bundle_zip.writestr("scripts/x.py", "print('hello')\n")
    stored = output.getvalue()
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.side_effect = [
        io.BytesIO(stored),
        io.BytesIO(_bundle("healthy")),
    ]
    validity_updates: list[push.SkillValidityUpdate] = []
    monkeypatch.setattr(push, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(push, "persist_skill_validity", validity_updates.extend)
    replacement = MagicMock(wraps=push.resolve_skill_dir_placeholder)
    monkeypatch.setattr(push, "resolve_skill_dir_placeholder", replacement)
    monkeypatch.setattr(push, "DEFAULT_PER_FILE_MAX_BYTES", 1_100, raising=False)
    oversized = _skill()
    healthy = _skill(name="healthy", is_valid=True)

    files = push._assemble_fileset(
        [oversized, healthy], cast(User, SimpleNamespace()), MagicMock(spec=Session)
    )

    assert set(files) == {"healthy/SKILL.md", "healthy/scripts/run.py"}
    assert files["healthy/scripts/run.py"] == b"print('hello')\n"
    replacement.assert_not_called()
    assert len(validity_updates) == 1
    assert validity_updates[0].skill_id == oversized.id
    assert validity_updates[0].bundle_file_id == "bundle-id"
    assert validity_updates[0].is_valid is True
    file_store.save_file.assert_not_called()
    assert output.getvalue() == stored
