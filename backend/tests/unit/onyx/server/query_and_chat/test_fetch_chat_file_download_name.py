"""Coverage for the download name `GET /chat/file/{file_id}` sends."""

from io import BytesIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Request, Response

from onyx.db.models import User
from onyx.server.query_and_chat.chat_backend import fetch_chat_file

FILE_ID = "chat-file-1"
PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def _setup(
    monkeypatch: pytest.MonkeyPatch, file_type: str, display_name: str | None
) -> None:
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
        file_type=file_type, display_name=display_name
    )
    file_store.read_file.return_value = BytesIO(b"payload")
    monkeypatch.setattr(
        "onyx.server.query_and_chat.chat_backend.get_default_file_store",
        lambda: file_store,
    )


def _call() -> Response:
    return fetch_chat_file(
        file_id=FILE_ID,
        request=cast(Request, SimpleNamespace(headers={})),
        parsed=False,
        user=cast(User, SimpleNamespace(id=uuid4())),
        db_session=MagicMock(),
    )


def test_generated_office_file_downloads_with_its_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch, PPTX_MIME_TYPE, display_name='Q3 "Deck"')

    response = _call()

    assert response.headers["content-type"] == PPTX_MIME_TYPE
    assert response.headers["content-disposition"] == (
        "inline; filename=\"Q3 _Deck_.pptx\"; filename*=UTF-8''Q3%20_Deck_.pptx"
    )


def test_file_without_display_name_is_named_after_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch, "text/csv", display_name=None)

    response = _call()

    assert response.headers["content-disposition"] == (
        f"inline; filename=\"{FILE_ID}.csv\"; filename*=UTF-8''{FILE_ID}.csv"
    )
