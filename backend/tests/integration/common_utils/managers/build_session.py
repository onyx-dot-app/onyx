"""HTTP wrapper for build-mode session endpoints.

Modeled on ``SkillManager``: a thin static façade that turns "create a session,
upload a file, send a message" into one method call from an integration test.
Each method calls the API server through the same ``user.headers`` /
``user.cookies`` auth pattern used elsewhere in ``common_utils.managers``.
"""

from __future__ import annotations

from typing import Any
from typing import NamedTuple
from uuid import UUID

from onyx.db.enums import SandboxStatus
from onyx.db.enums import SharingScope
from onyx.server.features.build.interactive_turns.models import InteractiveTurnResponse
from onyx.server.features.build.models import UploadResponse
from onyx.server.features.build.sandbox.models import DirectoryListing
from onyx.server.features.build.session.models import DetailedSessionResponse
from onyx.server.features.build.session.models import MessageListResponse
from onyx.server.features.build.session.models import MessageResponse
from onyx.server.features.build.session.models import OpencodeHistorySnapshotResponse
from onyx.server.features.build.session.models import SessionListResponse
from onyx.server.features.build.session.models import SessionResponse
from onyx.server.features.build.session.models import SnapshotResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


class SessionWithSandbox(NamedTuple):
    session_id: UUID
    sandbox_id: UUID


def _sessions_url(*parts: str) -> str:
    base = f"{API_SERVER_URL}/build/sessions"
    if not parts:
        return base
    return base + "/" + "/".join(parts)


def _build_url(*parts: str) -> str:
    return f"{API_SERVER_URL}/build/" + "/".join(parts)


class BuildSessionManager:
    """Static wrapper around the build-mode session HTTP API."""

    @staticmethod
    def create(
        user: DATestUser,
        *,
        headless: bool = True,
        **kwargs: Any,
    ) -> DetailedSessionResponse:
        # The endpoint returns the user's pre-provisioned empty session if
        # one exists. Tests need isolation per call, so delete any existing
        # empty session before creating fresh.
        body: dict[str, Any] = {"headless": headless, **kwargs}
        pre = client.post(
            _sessions_url(),
            json=body,
            headers=user.headers,
            cookies=user.cookies,
        )
        if not pre.is_error:
            client.delete(
                f"{_sessions_url()}/{pre.json()['id']}",
                headers=user.headers,
                cookies=user.cookies,
            )

        response = client.post(
            _sessions_url(),
            json=body,
            headers=user.headers,
            cookies=user.cookies,
        )
        if response.is_error:
            raise AssertionError(
                f"POST /build/sessions failed: {response.status_code} {response.reason_phrase} "
                f"— body: {response.text!r} (user_id={user.id}, role={user.role})"
            )
        return DetailedSessionResponse.model_validate(response.json())

    @staticmethod
    def create_with_sandbox(
        user: DATestUser,
        **kwargs: Any,
    ) -> SessionWithSandbox:
        """Create a session and return ``(session_id, sandbox_id)``.

        Asserts the response carries a RUNNING sandbox.
        """
        session = BuildSessionManager.create(user, **kwargs)
        sandbox = session.sandbox
        assert sandbox is not None, (
            f"session create did not return a sandbox: {session!r}"
        )
        assert sandbox.status == SandboxStatus.RUNNING, (
            f"session create returned a non-RUNNING sandbox: {sandbox!r}"
        )
        return SessionWithSandbox(
            session_id=UUID(session.id), sandbox_id=UUID(sandbox.id)
        )

    @staticmethod
    def list_sessions(user: DATestUser) -> list[SessionResponse]:
        response = client.get(
            _sessions_url(),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return SessionListResponse.model_validate(response.json()).sessions

    @staticmethod
    def restore(user: DATestUser, session_id: UUID) -> DetailedSessionResponse:
        response = client.post(
            _sessions_url(str(session_id), "restore"),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return DetailedSessionResponse.model_validate(response.json())

    @staticmethod
    def create_snapshot(user: DATestUser, session_id: UUID) -> SnapshotResponse | None:
        """POST /snapshot; ``None`` on 204 (session has no outputs to snapshot)."""
        response = client.post(
            _sessions_url(str(session_id), "snapshot"),
            headers=user.headers,
            cookies=user.cookies,
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return SnapshotResponse.model_validate(response.json())

    @staticmethod
    def create_opencode_history_snapshot(
        user: DATestUser, session_id: UUID
    ) -> OpencodeHistorySnapshotResponse:
        response = client.post(
            _sessions_url(str(session_id), "opencode-history-snapshot"),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return OpencodeHistorySnapshotResponse.model_validate(response.json())

    @staticmethod
    def start_turn(
        user: DATestUser,
        session_id: UUID,
        content: str,
        *,
        client_request_id: str | None = None,
    ) -> InteractiveTurnResponse:
        url = _build_url("sessions", str(session_id), "send-message")
        body: dict[str, Any] = {"content": content}
        if client_request_id is not None:
            body["client_request_id"] = client_request_id
        response = client.post(
            url,
            json=body,
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return InteractiveTurnResponse.model_validate(response.json())

    @staticmethod
    def get_active_turn(
        user: DATestUser,
        session_id: UUID,
    ) -> InteractiveTurnResponse | None:
        response = client.get(
            _build_url("sessions", str(session_id), "turns", "active"),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        body = response.json()
        return (
            InteractiveTurnResponse.model_validate(body) if body is not None else None
        )

    @staticmethod
    def list_messages(user: DATestUser, session_id: UUID) -> list[MessageResponse]:
        response = client.get(
            _build_url("sessions", str(session_id), "messages"),
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return MessageListResponse.model_validate(response.json()).messages

    @staticmethod
    def upload_file(
        user: DATestUser,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> UploadResponse:
        # File-upload endpoints require multipart; the session cookie still
        # works but Content-Type must be left to ``requests``.
        headers = {k: v for k, v in user.headers.items() if k.lower() != "content-type"}
        response = client.post(
            _sessions_url(str(session_id), "upload"),
            files={"file": (filename, content, "application/octet-stream")},
            headers=headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return UploadResponse.model_validate(response.json())

    @staticmethod
    def delete_file(
        user: DATestUser,
        session_id: UUID,
        path: str,
    ) -> None:
        response = client.delete(
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
    ) -> DirectoryListing:
        response = client.get(
            _sessions_url(str(session_id), "files"),
            params={"path": path} if path else None,
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
        return DirectoryListing.model_validate(response.json())

    @staticmethod
    def download_artifact(
        user: DATestUser,
        session_id: UUID,
        path: str,
    ) -> bytes:
        response = client.get(
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
        response = client.patch(
            _sessions_url(str(session_id), "public"),
            json={"sharing_scope": scope.value},
            headers=user.headers,
            cookies=user.cookies,
        )
        response.raise_for_status()
