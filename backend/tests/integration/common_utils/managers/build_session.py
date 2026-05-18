"""HTTP wrapper for build-mode session endpoints.

Modeled on ``SkillManager``: a thin static façade that turns "create a session,
upload a file, send a message" into one method call from an integration test.
Each method calls the API server through the same ``user.headers`` /
``user.cookies`` auth pattern used elsewhere in ``common_utils.managers``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import requests

from onyx.db.enums import SharingScope
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


def _sessions_url(*parts: str) -> str:
    base = f"{API_SERVER_URL}/build/sessions"
    if not parts:
        return base
    return base + "/" + "/".join(parts)


def _build_url(*parts: str) -> str:
    return f"{API_SERVER_URL}/build/" + "/".join(parts)


def _parse_sse_lines(response: requests.Response) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON payloads from an SSE stream.

    The send-message endpoint emits Server-Sent Events: ``data: {...}\\n\\n``.
    Lines without a ``data:`` prefix (comments, retry hints) are skipped.
    """
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        if raw_line.startswith("data:"):
            payload = raw_line[len("data:") :].strip()
            if not payload:
                continue
            yield json.loads(payload)


class BuildSessionManager:
    """Static wrapper around the build-mode session HTTP API."""

    @staticmethod
    def create(
        user: DATestUser,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = requests.post(
            _sessions_url(),
            json=kwargs,
            headers=user.headers,
            cookies=user.cookies,
        )
        if not response.ok:
            # Surface the response body so CI logs explain *which* 4xx/5xx
            # this is (auth vs. feature flag vs. permission vs. server error)
            # instead of just "403 Forbidden".
            raise AssertionError(
                f"POST /build/sessions failed: {response.status_code} {response.reason} "
                f"— body: {response.text!r} (user_id={user.id}, role={user.role})"
            )
        return response.json()

    @staticmethod
    def list_sessions(user: DATestUser) -> list[dict[str, Any]]:
        response = requests.get(
            _sessions_url(),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        body = response.json()
        # Endpoint returns ``SessionListResponse``; sessions live under
        # the ``sessions`` key.
        if isinstance(body, dict) and "sessions" in body:
            sessions = body["sessions"]
            assert isinstance(sessions, list)
            return sessions
        assert isinstance(body, list)
        return body

    @staticmethod
    def get(user: DATestUser, session_id: UUID) -> dict[str, Any]:
        response = requests.get(
            _sessions_url(str(session_id)),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete(user: DATestUser, session_id: UUID) -> None:
        response = requests.delete(
            _sessions_url(str(session_id)),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()

    @staticmethod
    def restore(user: DATestUser, session_id: UUID) -> dict[str, Any]:
        response = requests.post(
            _sessions_url(str(session_id), "restore"),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def send_message(
        user: DATestUser,
        session_id: UUID,
        content: str,
    ) -> Iterator[dict[str, Any]]:
        # send-message lives under /build/sessions/{id}/send-message but is
        # registered on the messages_router which mounts at /build (the
        # router itself declares the /sessions/... prefix).
        url = _build_url("sessions", str(session_id), "send-message")
        with requests.post(
            url,
            json={"content": content},
            headers=user.headers,
            cookies=user.cookies,
            stream=True,
        ) as response:
            response.raise_for_status()
            yield from _parse_sse_lines(response)

    @staticmethod
    def upload_file(
        user: DATestUser,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        # File-upload endpoints require multipart; the session cookie still
        # works but Content-Type must be left to ``requests``.
        headers = {k: v for k, v in user.headers.items() if k.lower() != "content-type"}
        response = requests.post(
            _sessions_url(str(session_id), "upload"),
            files={"file": (filename, content, "application/octet-stream")},
            headers=headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def delete_file(
        user: DATestUser,
        session_id: UUID,
        path: str,
    ) -> None:
        response = requests.delete(
            _sessions_url(str(session_id), "files", path),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()

    @staticmethod
    def list_files(
        user: DATestUser,
        session_id: UUID,
        path: str = "",
    ) -> dict[str, Any]:
        response = requests.get(
            _sessions_url(str(session_id), "files"),
            params={"path": path} if path else None,
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def download_artifact(
        user: DATestUser,
        session_id: UUID,
        path: str,
    ) -> bytes:
        response = requests.get(
            _sessions_url(str(session_id), "artifacts", path),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return response.content

    @staticmethod
    def set_sharing(
        user: DATestUser,
        session_id: UUID,
        scope: SharingScope,
    ) -> None:
        response = requests.patch(
            _sessions_url(str(session_id), "public"),
            json={"sharing_scope": scope.value},
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
