"""Coverage for the inline-MIME allowlist on `GET /chat/file/{file_id}` and
`POST /chat/file/{file_id}/preview`.

Uploads keep the content type the client declared, so serving one inline is a
stored-XSS primitive unless the type is inert. These tests pin the allowlist, the
attachment fallback, and the security headers on every response the endpoint can
return."""

from io import BytesIO
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.routing import Match

from onyx.db.models import User
from onyx.file_store.serving import RESPONSE_POLICY_VERSION
from onyx.server.query_and_chat.chat_backend import (
    fetch_chat_file,
    make_chat_file_preview,
    router,
)

FILE_ID = "chat-file-1"
CURRENT_ETAG = f'"{FILE_ID}-{RESPONSE_POLICY_VERSION}"'
# What the endpoint returned before it gained the security headers.
PRE_POLICY_ETAG = f'"{FILE_ID}"'


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    file_type: str,
    display_name: str | None = "report",
) -> MagicMock:
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
        file_id=FILE_ID, file_type=file_type, display_name=display_name
    )
    file_store.read_file.return_value = BytesIO(b"payload")
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_default_file_store",
        lambda: file_store,
    )
    return file_store


def _call(
    if_none_match: str | None = None,
    parsed: bool = False,
    preview: Literal["pdf"] | None = None,
) -> Response:
    headers = {"if-none-match": if_none_match} if if_none_match else {}
    return fetch_chat_file(
        file_id=FILE_ID,
        request=cast(Request, SimpleNamespace(headers=headers)),
        parsed=parsed,
        preview=preview,
        user=cast(User, SimpleNamespace(id=uuid4())),
        db_session=MagicMock(),
    )


def _setup_preview(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    """A deck with a stored preview PDF; return the mock lookup of its
    owning row and the mock conversion."""
    _setup(
        monkeypatch,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        display_name='Q3 "Deck".pptx',
    )
    resolve = MagicMock(
        return_value=(SimpleNamespace(preview_file_id="preview-1"), uuid4(), "")
    )
    convert = MagicMock(return_value=BytesIO(b"%PDF-1.7"))
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.resolve_chat_file_preview", resolve
    )
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.convert_chat_file_preview_pdf",
        convert,
    )
    return resolve, convert


@pytest.mark.parametrize("file_type", ["image/png", "application/pdf", "text/plain"])
def test_allowlisted_type_is_served_inline(
    monkeypatch: pytest.MonkeyPatch, file_type: str
) -> None:
    _setup(monkeypatch, file_type)

    response = _call()

    assert response.headers["content-type"].startswith(file_type)
    assert response.headers["content-disposition"].startswith("inline;")


def test_mime_parameters_are_ignored_by_the_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Generated images are stored as "image/png;base64"; they must stay inline.
    _setup(monkeypatch, "IMAGE/PNG; base64")

    response = _call()

    assert response.headers["content-type"] == "IMAGE/PNG; base64"
    assert response.headers["content-disposition"].startswith("inline;")


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
    assert response.headers["content-disposition"].startswith("attachment;")


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
    # A 304 updates the stored response, so it repeats the 200's disposition.
    assert response.headers["content-disposition"].startswith("attachment;")
    file_store.read_file.assert_not_called()


def test_pre_policy_etag_is_not_revalidated(monkeypatch: pytest.MonkeyPatch) -> None:
    # A client holding a response cached before the fix must be sent a fresh one.
    _setup(monkeypatch, "text/html")

    response = _call(if_none_match=PRE_POLICY_ETAG)

    assert response.status_code == 200
    assert response.headers["etag"] == CURRENT_ETAG
    assert response.headers["content-disposition"].startswith("attachment;")


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
    assert response.headers["etag"] == f'"{FILE_ID}-parsed-{RESPONSE_POLICY_VERSION}"'


def test_generated_office_file_downloads_with_its_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pptx_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    _setup(monkeypatch, pptx_type, display_name='Q3 "Deck"')

    response = _call()

    assert response.headers["content-type"] == pptx_type
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"Q3 _Deck_.pptx\"; filename*=UTF-8''Q3%20_Deck_.pptx"
    )


def test_file_without_display_name_is_named_after_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch, "text/csv", display_name=None)

    response = _call()

    assert response.headers["content-disposition"] == (
        f"attachment; filename=\"{FILE_ID}.csv\"; filename*=UTF-8''{FILE_ID}.csv"
    )


def test_preview_pdf_is_served_inline_as_a_pdf_named_after_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_preview(monkeypatch)

    response = _call(preview="pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        "inline; filename=\"Q3 _Deck_.pdf\"; filename*=UTF-8''Q3%20_Deck_.pdf"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["etag"] == (
        f'"{FILE_ID}-preview-pdf-{RESPONSE_POLICY_VERSION}"'
    )


def test_preview_pdf_not_modified_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve, _ = _setup_preview(monkeypatch)

    response = _call(
        if_none_match=f'"{FILE_ID}-preview-pdf-{RESPONSE_POLICY_VERSION}"',
        preview="pdf",
    )

    assert response.status_code == 304
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["content-security-policy"] == "sandbox"
    resolve.assert_not_called()


def test_a_made_preview_pdf_is_inline_and_never_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, convert = _setup_preview(monkeypatch)

    response = make_chat_file_preview(
        file_id=FILE_ID,
        user=cast(User, SimpleNamespace(id=uuid4())),
        db_session=MagicMock(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        "inline; filename=\"Q3 _Deck_.pdf\"; filename*=UTF-8''Q3%20_Deck_.pdf"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["cache-control"] == "private, no-store"
    assert "etag" not in response.headers
    convert.assert_called_once()


def test_the_preview_post_takes_a_file_id_with_a_slash() -> None:
    """The GET's path converter does not take the POST's path."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat/file/dir/deck.pptx/preview",
        "root_path": "",
    }
    [(endpoint, path_params)] = [
        (route.endpoint, child["path_params"])
        for route in router.routes
        if isinstance(route, APIRoute)
        for match, child in [route.matches(scope)]
        if match is Match.FULL
    ]

    assert endpoint is make_chat_file_preview
    assert path_params == {"file_id": "dir/deck.pptx"}
