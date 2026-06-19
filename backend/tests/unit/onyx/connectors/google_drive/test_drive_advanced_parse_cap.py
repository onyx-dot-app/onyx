"""get_document_sections bounds the Docs-API fetch: it returns None once the
streamed response exceeds the byte cap, and parses normally under it."""

import json
from unittest.mock import MagicMock

import pytest

from onyx.connectors.google_drive import section_extraction
from onyx.connectors.google_drive.section_extraction import get_document_sections


def _as_ctx(obj: MagicMock) -> MagicMock:
    obj.__enter__ = MagicMock(return_value=obj)
    obj.__exit__ = MagicMock(return_value=False)
    return obj


def _mock_session(chunks: list[bytes]) -> MagicMock:
    response = _as_ctx(MagicMock())
    response.raise_for_status = MagicMock()
    response.iter_content = MagicMock(return_value=iter(chunks))
    session = _as_ctx(MagicMock())
    session.get = MagicMock(return_value=response)
    return session


def _patch(monkeypatch: pytest.MonkeyPatch, session: MagicMock) -> None:
    monkeypatch.setattr(
        section_extraction,
        "get_impersonated_creds",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        section_extraction, "AuthorizedSession", MagicMock(return_value=session)
    )


def test_get_document_sections_returns_none_over_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, _mock_session([b"a" * 80, b"b" * 80]))
    result = get_document_sections(
        creds=MagicMock(),
        doc_id="doc",
        user_email="u@example.com",
        max_response_bytes=100,
    )
    assert result is None


def test_get_document_sections_parses_under_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, _mock_session([json.dumps({"tabs": []}).encode()]))
    result = get_document_sections(
        creds=MagicMock(),
        doc_id="doc",
        user_email="u@example.com",
        max_response_bytes=10_000,
    )
    assert result == []
