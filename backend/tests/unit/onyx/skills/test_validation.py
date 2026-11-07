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
from onyx.skills.bundle import normalize_custom_bundle
from onyx.skills.validation import validate_stored_custom_skill


def test_stored_read_accepts_zip_larger_than_extracted_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation, "DEFAULT_TOTAL_MAX_BYTES", 1024)
    monkeypatch.setattr(validation, "DEFAULT_ZIP_MAX_BYTES", 4096, raising=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr(
            "SKILL.md", b"---\nname: canonical-name\ndescription: Limits\n---\n\nBody"
        )
        for index in range(10):
            zf.writestr(f"{index}.txt", b"a" * 80)
    stored = normalize_custom_bundle(
        buf.getvalue(), zip_max_bytes=4096, total_max_bytes=1024
    ).content
    assert 1024 < len(stored) < 4096
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored)
    assert (
        validation.load_stored_custom_skill_bundle("id", file_store).content == stored
    )


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
