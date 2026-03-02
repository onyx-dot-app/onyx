"""Async HTTP client for the Onyx API."""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import httpx

from onyx_cli.config import OnyxCliConfig
from onyx_cli.models import (
    CategorizedFilesSnapshot,
    ChatSessionCreationInfo,
    ChatSessionDetailResponse,
    ChatSessionDetails,
    ChatFileType,
    FileDescriptorPayload,
    PersonaSummary,
    SendMessagePayload,
    StreamEvent,
)
from onyx_cli.stream_parser import parse_stream_line


class OnyxApiError(Exception):
    """Raised when an Onyx API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class OnyxApiClient:
    """Async client for communicating with the Onyx server."""

    def __init__(self, config: OnyxCliConfig) -> None:
        self._config = config
        self._base_url = config.server_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            if self._config.api_key:
                bearer = f"Bearer {self._config.api_key}"
                headers["Authorization"] = bearer
                # Some reverse proxies / ingress controllers strip the
                # Authorization header.  The Onyx backend also checks
                # X-Onyx-Authorization as a fallback, so send both.
                headers["X-Onyx-Authorization"] = bearer
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0, read=120.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def update_config(self, config: OnyxCliConfig) -> None:
        """Update the client config. Closes existing connection."""
        self._config = config
        self._base_url = config.server_url.rstrip("/")
        if self._client and not self._client.is_closed:
            # Will be lazily recreated on next request
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._client.aclose())
            except RuntimeError:
                pass
            self._client = None

    # ── Health / Connection Test ─────────────────────────────────────

    async def test_connection(self) -> tuple[bool, str]:
        """Test if the server is reachable and credentials are valid.

        Returns (success, detail_message).
        """
        # Step 1: Basic reachability — hit the base URL to check network
        # access.  A proxy/WAF that blocks everything will fail here.
        try:
            probe = await self.client.get("/", follow_redirects=True)
        except httpx.ConnectError:
            return False, f"Cannot connect to {self._base_url}. Is the server running?"
        except httpx.TimeoutException:
            return False, f"Connection to {self._base_url} timed out."
        except httpx.HTTPError as e:
            return False, f"Connection error: {e}"

        server_header = (probe.headers.get("server") or "").lower()

        # If even the base URL returns 403, it's a network-level block
        # (WAF, ALB security group, IP allowlist, etc.)
        if probe.status_code == 403:
            if "awselb" in server_header or "amazons3" in server_header:
                return False, (
                    "Blocked by AWS load balancer (HTTP 403 on all requests).\n"
                    "  Your IP address may not be in the ALB's security group or WAF allowlist.\n"
                    "  Try connecting from an allowed network or VPN, or ask your admin\n"
                    "  to allowlist your IP."
                )
            return False, (
                f"HTTP 403 on base URL — the server is blocking all traffic.\n"
                f"  This is likely a firewall, WAF, or IP allowlist restriction.\n"
                f"  Try connecting from an allowed network or VPN."
            )

        # Step 2: Authenticated check — call an endpoint that requires
        # a valid API key / token.
        try:
            resp = await self.client.get("/api/chat/get-user-chat-sessions")
        except httpx.TimeoutException:
            return False, "Server reachable but API request timed out."
        except httpx.HTTPError as e:
            return False, f"Server reachable but API error: {e}"

        if resp.status_code == 200:
            return True, "Connected and authenticated."

        # Non-200: build a diagnostic message
        body = resp.text[:300]
        is_html = body.strip().startswith("<")
        resp_server = (resp.headers.get("server") or "").lower()

        if resp.status_code in (401, 403):
            if is_html or "awselb" in resp_server:
                # HTML error page or ALB response means a proxy is blocking.
                return False, (
                    f"HTTP {resp.status_code} from a reverse proxy (not the Onyx backend).\n"
                    "  This usually means the deployment has an additional auth layer\n"
                    "  (e.g. ingress auth, WAF, or OAuth proxy) in front of Onyx.\n"
                    "  Check your deployment's ingress / proxy configuration,\n"
                    "  or try connecting directly to the Onyx backend port."
                )
            else:
                hint = (
                    "Invalid API key or token."
                    if resp.status_code == 401
                    else "Access denied — check that the API key is valid and has sufficient permissions."
                )
                return False, f"{hint}\n  {body}"
        else:
            detail = f"HTTP {resp.status_code} from {resp.url}"
            if body:
                detail += f"\n  Response: {body}"
            return False, detail

    # ── Personas ─────────────────────────────────────────────────────

    async def list_personas(self) -> list[PersonaSummary]:
        """Get available personas/assistants."""
        resp = await self.client.get("/api/persona")
        resp.raise_for_status()
        raw_list = resp.json()
        return [
            PersonaSummary(
                id=p["id"],
                name=p["name"],
                description=p.get("description", ""),
                is_default_persona=p.get("is_default_persona", False),
            )
            for p in raw_list
            if p.get("is_visible", True)
        ]

    # ── Chat Sessions ────────────────────────────────────────────────

    async def list_chat_sessions(self) -> list[ChatSessionDetails]:
        """Get recent chat sessions."""
        resp = await self.client.get("/api/chat/get-user-chat-sessions")
        resp.raise_for_status()
        data = resp.json()
        sessions = data.get("sessions", [])
        return [
            ChatSessionDetails(
                id=s["id"],
                name=s.get("name"),
                persona_id=s.get("persona_id"),
                time_created=s.get("time_created", ""),
                time_updated=s.get("time_updated", ""),
            )
            for s in sessions
        ]

    async def get_chat_session(self, session_id: UUID) -> ChatSessionDetailResponse:
        """Get full details for a chat session including messages."""
        resp = await self.client.get(f"/api/chat/get-chat-session/{session_id}")
        resp.raise_for_status()
        data = resp.json()
        return ChatSessionDetailResponse(**data)

    # ── File Upload ──────────────────────────────────────────────────

    async def upload_file(self, file_path: Path) -> FileDescriptorPayload:
        """Upload a file and return a file descriptor for use in messages."""
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            files = {"files": (file_path.name, f, mime_type)}
            resp = await self.client.post(
                "/api/user/projects/file/upload",
                files=files,
                timeout=httpx.Timeout(60.0),
            )

        resp.raise_for_status()
        snapshot = CategorizedFilesSnapshot(**resp.json())

        if not snapshot.user_files:
            raise OnyxApiError(400, "File upload returned no files")

        uf = snapshot.user_files[0]
        return FileDescriptorPayload(
            id=uf.file_id,
            type=uf.chat_file_type,
            name=file_path.name,
        )

    # ── Send Message (Streaming) ─────────────────────────────────────

    async def send_message_stream(
        self,
        message: str,
        chat_session_id: UUID | None = None,
        persona_id: int = 0,
        parent_message_id: int | None = -1,
        file_descriptors: list[FileDescriptorPayload] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Send a chat message and yield streaming events."""
        payload = SendMessagePayload(
            message=message,
            parent_message_id=parent_message_id,
            file_descriptors=[
                {"id": fd.id, "type": fd.type.value, "name": fd.name}
                for fd in (file_descriptors or [])
            ],
        )

        if chat_session_id is not None:
            payload.chat_session_id = str(chat_session_id)
        else:
            payload.chat_session_info = ChatSessionCreationInfo(persona_id=persona_id)

        async with self.client.stream(
            "POST",
            "/api/chat/send-chat-message",
            json=payload.model_dump(exclude_none=True),
            timeout=httpx.Timeout(30.0, read=300.0),
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise OnyxApiError(response.status_code, body.decode(errors="replace"))

            async for line in response.aiter_lines():
                event = parse_stream_line(line)
                if event is not None:
                    yield event

    # ── Stop Chat Session ────────────────────────────────────────────

    async def stop_chat_session(self, session_id: UUID) -> None:
        """Send stop signal for a streaming chat session."""
        try:
            resp = await self.client.post(f"/api/chat/stop-chat-session/{session_id}")
            resp.raise_for_status()
        except httpx.HTTPError:
            pass  # Best-effort
