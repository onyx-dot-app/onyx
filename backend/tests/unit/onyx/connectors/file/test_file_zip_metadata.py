"""The zip metadata loader accepts a dict, or a list of entries keyed by file
name. Other content raises in strict mode and counts as empty otherwise."""

import json
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.file import metadata
from onyx.connectors.file.metadata import ZipMetadataError, load_zip_metadata


def _store_holding(content: bytes) -> MagicMock:
    store = MagicMock()
    store.read_file.return_value = BytesIO(content)
    return store


@pytest.mark.parametrize(
    "loaded, expected",
    [
        ({"a.txt": {"title": "A"}}, {"a.txt": {"title": "A"}}),
        (
            [{"filename": "a.txt", "title": "A"}],
            {"a.txt": {"filename": "a.txt", "title": "A"}},
        ),
    ],
)
def test_accepted_shapes(
    monkeypatch: pytest.MonkeyPatch, loaded: Any, expected: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        metadata,
        "get_default_file_store",
        lambda: _store_holding(json.dumps(loaded).encode()),
    )

    assert load_zip_metadata("meta", None, strict=True) == expected


@pytest.mark.parametrize(
    "content",
    [b"null", b"[1]", b'[{"title": "no filename"}]', b"not json"],
)
def test_wrong_shapes_raise_in_strict_mode_only(
    monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    monkeypatch.setattr(
        metadata, "get_default_file_store", lambda: _store_holding(content)
    )

    with pytest.raises(ZipMetadataError):
        load_zip_metadata("meta", None, strict=True)
    assert load_zip_metadata("meta", None) == {}


def test_unreadable_file_raises_in_strict_mode_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    store.read_file.side_effect = RuntimeError("missing")
    monkeypatch.setattr(metadata, "get_default_file_store", lambda: store)

    with pytest.raises(ZipMetadataError):
        load_zip_metadata("meta", None, strict=True)
    assert load_zip_metadata("meta", None) == {}
