"""get_document_sections bounds the Docs-API fetch: it returns None once the
streamed response exceeds the byte cap, and parses normally under it."""

import json
from unittest.mock import MagicMock

from onyx.connectors.google_drive.section_extraction import get_document_sections


def _as_ctx(obj: MagicMock) -> MagicMock:
    obj.__enter__ = MagicMock(return_value=obj)
    obj.__exit__ = MagicMock(return_value=False)
    return obj


def _mock_session(chunks: list[bytes]) -> MagicMock:
    response = _as_ctx(MagicMock())
    response.raise_for_status = MagicMock()
    response.iter_content = MagicMock(return_value=iter(chunks))
    session = MagicMock()
    session.get = MagicMock(return_value=response)
    return session


def test_get_document_sections_returns_none_over_cap() -> None:
    result = get_document_sections(
        authorized_session=_mock_session([b"a" * 80, b"b" * 80]),
        doc_id="doc",
        max_response_bytes=100,
    )
    assert result is None


def test_get_document_sections_parses_under_cap() -> None:
    result = get_document_sections(
        authorized_session=_mock_session([json.dumps({"tabs": []}).encode()]),
        doc_id="doc",
        max_response_bytes=10_000,
    )
    assert result == []
