"""Coverage for the inline-MIME allowlist on `GET /chat/file/{file_id}`.

Uploads keep the content type the client declared, so serving one inline is a
stored-XSS primitive unless the type is inert. These tests pin the allowlist, the
attachment fallback, and the security headers on every response the endpoint can
return."""

from io import BytesIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Request, Response

from onyx.db.models import User
from onyx.server.query_and_chat.chat_backend import (
    _RESPONSE_POLICY_VERSION,
    fetch_chat_file,
)

FILE_ID = "chat-file-1"
CURRENT_ETAG = f'"{FILE_ID}-{_RESPONSE_POLICY_VERSION}"'
# What the endpoint returned before it gained the security headers.
PRE_POLICY_ETAG = f'"{FILE_ID}"'


def _setup(monkeypatch: pytest.MonkeyPatch, file_type: str) -> MagicMock:
    """Patch the access checks and the file store; return the mock store."""
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_file_id_by_user_file_id",
        lambda *_: None,
    )
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.user_can_access_chat_file",
        lambda *_: True,
    )

    file_store = MagicMock()
    file_store.read_file_record.return_value = SimpleNamespace(
        file_type=file_type, display_name="report"
    )
    file_store.read_file.return_value = BytesIO(b"payload")
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_default_file_store",
        lambda: file_store,
    )
    return file_store


def _call(if_none_match: str | None = None, parsed: bool = False) -> Response:
    headers = {"if-none-match": if_none_match} if if_none_match else {}
    return fetch_chat_file(
        file_id=FILE_ID,
        request=cast(Request, SimpleNamespace(headers=headers)),
        parsed=parsed,
        user=cast(User, SimpleNamespace(id=uuid4())),
        db_session=MagicMock(),
    )


@pytest.mark.parametrize("file_type", ["image/png", "application/pdf", "text/plain"])
def test_allowlisted_type_is_served_inline(
    monkeypatch: pytest.MonkeyPatch, file_type: str
) -> None:
    _setup(monkeypatch, file_type)

    response = _call()

    assert response.headers["content-type"].startswith(file_type)
    assert "content-disposition" not in response.headers


def test_mime_parameters_are_ignored_by_the_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Generated images are stored as "image/png;base64"; they must stay inline.
    _setup(monkeypatch, "IMAGE/PNG; base64")

    response = _call()

    assert response.headers["content-type"] == "IMAGE/PNG; base64"
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize(
    "file_type",
    ["text/html", "image/svg+xml", "application/xhtml+xml", "text/html; charset=utf-8"],
)
def test_active_content_is_forced_to_download(
    monkeypatch: pytest.MonkeyPatch, file_type: str
) -> None:
    _setup(monkeypatch, file_type)

    response = _call()

    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == "attachment"


@pytest.mark.parametrize("file_type", ["image/png", "text/html"])
def test_security_headers_on_the_streamed_response(
    monkeypatch: pytest.MonkeyPatch, file_type: str
) -> None:
    _setup(monkeypatch, file_type)

    response = _call()

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


def test_security_headers_on_the_parsed_spreadsheet_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(
        monkeypatch,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.parse_spreadsheet_for_preview",
        lambda *_: SimpleNamespace(model_dump=lambda: {"rows": []}),
    )

    response = _call(parsed=True)

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


def test_security_headers_on_the_not_modified_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = _setup(monkeypatch, "text/html")

    response = _call(if_none_match=CURRENT_ETAG)

    assert response.status_code == 304
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    file_store.read_file.assert_not_called()


def test_pre_policy_etag_is_not_revalidated(monkeypatch: pytest.MonkeyPatch) -> None:
    # A client holding a response cached before the fix must be sent a fresh one.
    _setup(monkeypatch, "text/html")

    response = _call(if_none_match=PRE_POLICY_ETAG)

    assert response.status_code == 200
    assert response.headers["etag"] == CURRENT_ETAG
    assert response.headers["content-disposition"] == "attachment"


def test_parsed_spreadsheet_etag_is_versioned(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(
        monkeypatch,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.parse_spreadsheet_for_preview",
        lambda *_: SimpleNamespace(model_dump=lambda: {"rows": []}),
    )

    response = _call(if_none_match=f'"{FILE_ID}-parsed"', parsed=True)

    assert response.status_code == 200
    assert response.headers["etag"] == f'"{FILE_ID}-parsed-{_RESPONSE_POLICY_VERSION}"'
