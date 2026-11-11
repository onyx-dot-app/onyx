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
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills import bundle, validation
from onyx.skills.bundle import normalize_custom_bundle
from onyx.skills.validation import validate_stored_custom_skill


def test_stored_read_accepts_zip_larger_than_extracted_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation, "DEFAULT_STORED_ZIP_MAX_BYTES", 4096)
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

    monkeypatch.setattr(bundle, "DEFAULT_ZIP_MAX_BYTES", 1024)
    file_store.read_file.return_value = io.BytesIO(stored)
    assert (
        validation.load_stored_custom_skill_bundle("id", file_store).content == stored
    )
    with pytest.raises(OnyxError):
        bundle.read_bundle_file(io.BytesIO(stored), filename="skill.zip")


def test_stored_read_still_enforces_its_own_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation, "DEFAULT_STORED_ZIP_MAX_BYTES", 1024)
    stream = io.BytesIO(b"x" * 1025)
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = stream
    with pytest.raises(OnyxError) as exc:
        validation.load_stored_custom_skill_bundle("id", file_store)
    assert exc.value.extra == {"limit": "zip_bytes", "limit_value": 1024}
    assert stream.closed


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


def test_bundle_over_lowered_stored_allowance_stays_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _valid_stored_bundle()
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored)
    monkeypatch.setattr(validation, "DEFAULT_STORED_ZIP_MAX_BYTES", len(stored) - 1)

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is None
    assert result.normalized_bundle is None

    # Object metadata rejects the bundle without a download.
    file_store.get_file_size.return_value = len(stored)
    file_store.read_file.reset_mock()
    assert validate_stored_custom_skill(_skill(), file_store).is_valid is None
    file_store.read_file.assert_not_called()

    monkeypatch.setattr(validation, "DEFAULT_STORED_ZIP_MAX_BYTES", len(stored))
    file_store.read_file.return_value = io.BytesIO(stored)
    assert validate_stored_custom_skill(_skill(), file_store).is_valid is True


def test_invalid_bundle_settings_leave_skill_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(_valid_stored_bundle())
    monkeypatch.setattr(bundle, "SKILL_BUNDLE_SETTINGS_ERROR", "settings are invalid")

    result = validate_stored_custom_skill(_skill(), file_store)

    assert result.is_valid is None
    assert result.normalized_bundle is None
