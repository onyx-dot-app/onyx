from __future__ import annotations

import io
import os
import zipfile
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import Skill
from onyx.file_store.file_store import FileStore
from onyx.skills import validation
from onyx.skills.validation import validate_stored_custom_skill


def _skill(name: str = "canonical-name") -> Skill:
    return cast(
        Skill,
        SimpleNamespace(
            id=uuid4(),
            name=name,
            bundle_file_id="bundle-id",
        ),
    )


def test_missing_bundle_is_invalid() -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.side_effect = FileRecordNotFoundError("missing")

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is False
    assert result.normalized_bundle is None


def test_transient_bundle_read_remains_unclassified() -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.side_effect = TimeoutError("temporary outage")

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is None
    assert result.normalized_bundle is None


def test_malformed_bundle_is_invalid() -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(b"not a zip")

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is False
    assert result.normalized_bundle is None


def test_bundle_stored_before_zip_and_file_count_limits_still_loads() -> None:
    mib = 1024 * 1024
    skill_md = b"---\nname: canonical-name\ndescription: Older skill\n---\n\nBody\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("SKILL.md", skill_md)
        zf.writestr("a.bin", os.urandom(13 * mib))
        zf.writestr("b.bin", os.urandom(13 * mib))
        for index in range(600):
            zf.writestr(f"refs/{index}.md", b"x")
    stored_bundle = buf.getvalue()
    assert len(stored_bundle) > 26 * mib
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored_bundle)

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is True
    assert result.normalized_bundle == stored_bundle


def _valid_stored_bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("SKILL.md", b"---\nname: canonical-name\ndescription: x\n---\n")
        zf.writestr("data.txt", b"a" * 2048)
    return buf.getvalue()


def test_bundle_over_lowered_total_limit_stays_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _valid_stored_bundle()
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored)
    monkeypatch.setattr(validation, "DEFAULT_TOTAL_MAX_BYTES", len(stored) - 1)

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is None
    assert result.normalized_bundle is None

    monkeypatch.setattr(validation, "DEFAULT_TOTAL_MAX_BYTES", len(stored))
    file_store.read_file.return_value = io.BytesIO(stored)
    assert validate_stored_custom_skill(_skill(), file_store).is_valid is True
