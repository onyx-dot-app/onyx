"""Shared HTTP helpers for the user-library endpoints."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable

import httpx

from onyx.server.features.build.user_library.api import LibraryEntryResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


def _url(*parts: str) -> str:
    return f"{API_SERVER_URL}/build/user-library/" + "/".join(parts)


def multipart_headers(user: DATestUser) -> dict[str, str]:
    """Drop the JSON Content-Type so the client can set the multipart one."""
    return {k: v for k, v in user.headers.items() if k.lower() != "content-type"}


def upload_user_library_files(
    user: DATestUser,
    files: Iterable[tuple[str, bytes, str | None]],
    path: str = "/",
) -> httpx.Response:
    multipart = [
        (
            "files",
            (name, io.BytesIO(content), content_type or "application/octet-stream"),
        )
        for name, content, content_type in files
    ]
    return client.post(
        _url("upload"),
        files=multipart,
        data={"path": path},
        headers=multipart_headers(user),
        cookies=user.cookies,
    )


def upload_user_library_zip(
    user: DATestUser,
    zip_bytes: bytes,
    path: str = "/",
    filename: str = "bundle.zip",
) -> httpx.Response:
    return client.post(
        _url("upload-zip"),
        files={"file": (filename, io.BytesIO(zip_bytes), "application/zip")},
        data={"path": path},
        headers=multipart_headers(user),
        cookies=user.cookies,
    )


def list_user_library_tree(user: DATestUser) -> list[LibraryEntryResponse]:
    response = client.get(
        _url("tree"),
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return [LibraryEntryResponse.model_validate(entry) for entry in response.json()]


def delete_user_library_file(user: DATestUser, document_id: str) -> httpx.Response:
    return client.delete(
        _url("files", document_id),
        headers=user.headers,
        cookies=user.cookies,
    )


def make_zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()
