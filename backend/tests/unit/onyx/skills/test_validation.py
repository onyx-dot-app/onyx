from __future__ import annotations

import io
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import Skill
from onyx.file_store.file_store import FileStore
from onyx.skills.validation import validate_stored_custom_skill


def _skill(slug: str = "canonical-name") -> Skill:
    return cast(
        Skill,
        SimpleNamespace(
            id=uuid4(),
            slug=slug,
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
