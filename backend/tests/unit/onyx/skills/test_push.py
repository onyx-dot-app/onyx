from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.models import User
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
    slug: str = "canonical-name",
    is_valid: bool | None = None,
) -> Skill:
    return cast(
        Skill,
        SimpleNamespace(
            id=uuid4(),
            slug=slug,
            name=slug,
            bundle_file_id="bundle-id",
            built_in_skill_id=None,
            is_valid=is_valid,
        ),
    )


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

    hydrated_skills, files = push._assemble_fileset(
        [skill], user, MagicMock(spec=Session)
    )

    assert hydrated_skills == [skill]
    assert files["canonical-name/scripts/run.py"] == b"print('hello')\n"
    assert b"license: Apache-2.0" in files["canonical-name/SKILL.md"]
    assert b"x-custom: retained" in files["canonical-name/SKILL.md"]
    assert skill.is_valid is None
    persist.assert_called_once_with(
        [
            push.SkillValidityUpdate(
                skill_id=skill.id,
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

    hydrated_skills, files = push._assemble_fileset(
        [skill], user, MagicMock(spec=Session)
    )

    assert hydrated_skills == []
    assert files == {}
    assert skill.is_valid is None
    persist.assert_called_once_with(
        [
            push.SkillValidityUpdate(
                skill_id=skill.id,
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

    hydrated_skills, files = push._assemble_fileset(
        [skill], user, MagicMock(spec=Session)
    )

    assert hydrated_skills == []
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

    hydrated_skills, files = push._assemble_fileset(
        [skill], user, MagicMock(spec=Session)
    )

    assert hydrated_skills == []
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

    hydrated_skills, files = push._assemble_fileset(
        [skill], user, MagicMock(spec=Session)
    )

    assert hydrated_skills == [skill]
    assert files["canonical-name/SKILL.md"].startswith(b"---\n")
    assert files["canonical-name/scripts/run.py"] == b"print('hello')\n"
    assert "canonical-name/canonical-name/SKILL.md" not in files
    persist.assert_called_once_with([])
    validate.assert_not_called()


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

    hydrated_skills, files = push._assemble_fileset(
        [skill], user, MagicMock(spec=Session)
    )

    assert hydrated_skills == [skill]
    assert files["canonical-name/SKILL.md"].startswith(b"---\n")


def test_user_payload_advertises_only_hydrated_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_skill = _skill(is_valid=True)
    invalid_skill = _skill(slug="invalid-skill", is_valid=False)
    user = cast(User, SimpleNamespace())
    db_session = MagicMock(spec=Session)
    build_section = MagicMock(return_value="skills section")

    monkeypatch.setattr(
        push,
        "list_skills",
        lambda **_kwargs: [valid_skill, invalid_skill],
    )
    monkeypatch.setattr(
        push,
        "_assemble_fileset",
        lambda *_args: ([valid_skill], {"canonical-name/SKILL.md": b"content"}),
    )
    monkeypatch.setattr(push, "build_skills_section_from_data", build_section)
    monkeypatch.setattr(push, "get_connectable_apps_for_user", lambda *_args: [])
    monkeypatch.setattr(push, "build_connectable_apps_list", lambda _apps: "apps")

    skills_section, apps_section, files = push.build_user_skills_payload(
        user, db_session
    )

    assert skills_section == "skills section"
    assert apps_section == "apps"
    assert files == {"canonical-name/SKILL.md": b"content"}
    build_section.assert_called_once_with([valid_skill])
