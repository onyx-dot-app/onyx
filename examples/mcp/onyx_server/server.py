"""Model Context Protocol server that proxies to Onyx's chat API.

The server exposes a single MCP tool, ``onyx_chat``, that sends a question to
Onyx's ``/chat/send-message`` endpoint. A fresh chat session is created on every
invocation so the only value supplied by the LLM is the question string. The
tool returns the composed answer text and any top documents surfaced during the
streamed response.

Environment variables used:
    - ``ONYX_API_BASE_URL``: Base URL for the Onyx deployment. Defaults to
      ``http://localhost:3000/api``.
    - ``ONYX_API_KEY``: Bearer token for authenticating with the Onyx API. The
      tool will raise an error if authentication is required but the key is not
      provided.

The script can also be configured via CLI flags. Run ``python server.py --help``
for details.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from typing import Optional

import httpx
from fastmcp import FastMCP


logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:3000/api"


class OnyxAPIError(RuntimeError):
    """Raised when the Onyx API returns an error payload."""


@dataclass
class OnyxConfig:
    base_url: str
    api_key: Optional[str]
    default_persona_id: int

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def join(self, path: str) -> str:
        """Join the base URL with an API path."""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url.rstrip('/')}{path}"


class OnyxClient:
    """Thin async HTTP client for creating sessions and sending chat messages."""

    def __init__(self, config: OnyxConfig) -> None:
        self._config = config
        # Use a single reusable client – it is safe for concurrent use.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=120.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_chat_session(self, persona_id: Optional[int]) -> str:
        payload = {"persona_id": persona_id or self._config.default_persona_id}
        url = self._config.join("/chat/create-chat-session")
        response = await self._client.post(
            url, json=payload, headers=self._config.headers()
        )
        response.raise_for_status()
        session_id = response.json()["chat_session_id"]
        return str(session_id)

    async def stream_chat_message(
        self,
        *,
        chat_session_id: str,
        message: str,
        retrieval_options: dict[str, Any],
        chunk_overrides: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_session_id": chat_session_id,
            "parent_message_id": None,
            "message": message,
            "file_descriptors": [],
            "user_file_ids": [],
            "user_folder_ids": [],
            "search_doc_ids": None,
            "retrieval_options": retrieval_options,
            **chunk_overrides,
        }

        # Keep all fields as the cloud API requires them
        # payload = {k: v for k, v in payload.items() if v is not None}

        url = self._config.join("/chat/send-message")
        headers = self._config.headers() | {"Accept": "text/event-stream"}

        answer_parts: list[str] = []
        top_documents: list[dict[str, Any]] | None = None

        async with self._client.stream(
            "POST", url, json=payload, headers=headers
        ) as response:
            response.raise_for_status()
            async for line in _iter_sse_lines(response.aiter_lines()):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Skipping non-JSON line from stream: %s", line)
                    continue

                if "error" in data:
                    raise OnyxAPIError(data["error"])

                # Handle the new streaming format
                obj = data.get("obj", {})
                obj_type = obj.get("type")

                # Extract message content from message_delta objects
                if obj_type == "message_delta":
                    content = obj.get("content")
                    if content:
                        answer_parts.append(content)

                # Extract final documents from message_start objects
                elif obj_type == "message_start":
                    final_documents = obj.get("final_documents")
                    if final_documents:
                        top_documents = final_documents

                # Legacy support for old format
                answer_piece = data.get("answer_piece")
                if answer_piece:
                    answer_parts.append(answer_piece)

                if "top_documents" in data and data["top_documents"]:
                    top_documents = data["top_documents"]

        return {
            "answer": "".join(answer_parts),
            "top_documents": top_documents or [],
        }


async def _iter_sse_lines(source: AsyncIterator[str]) -> AsyncIterator[str]:
    """Normalize the SSE stream to yield raw JSON strings."""
    async for raw_line in source:
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(":"):
            # Comment/keepalive
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            continue
        yield line


def build_mcp_server(config: OnyxConfig) -> FastMCP:
    client = OnyxClient(config)
    mcp = FastMCP("Onyx MCP Server")

    @mcp.tool(
        name="onyx_chat",
        description=(
            "Search Onyx internal knowledge base for company information. Use this tool for ANY questions about "
            "the Onyx office, employees, team members, company culture, internal discussions, workplace activities, "
            "office events, internal communications, company policies, team dynamics, or any company-specific "
            "information. This includes questions about who works at Onyx, what people are working on, office "
            "activities like ping pong games, internal chat discussions, team relationships, and general "
            "workplace-related queries. A new chat session is created for every invocation."
        ),
    )
    async def onyx_chat(question: str) -> dict[str, Any]:
        """Send a prompt to Onyx and return the concatenated answer and top documents."""

        chat_session_id = await client.create_chat_session(persona_id=None)

        retrieval_options = {
            "run_search": "always",
            "real_time": True,
            "enable_auto_detect_filters": False,
            "filters": {},
        }

        results = await client.stream_chat_message(
            chat_session_id=chat_session_id,
            message=question,
            retrieval_options=retrieval_options,
            chunk_overrides={},
        )

        return {
            "answer": results["answer"],
            "top_documents": results["top_documents"],
        }

    return mcp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Onyx MCP server")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ONYX_API_BASE_URL", DEFAULT_BASE_URL),
        help="Base URL for the Onyx API (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ONYX_API_KEY"),
        help="Bearer token for Onyx API authentication (default: env ONYX_API_KEY)",
    )
    parser.add_argument(
        "--persona-id",
        type=int,
        default=int(os.environ.get("ONYX_DEFAULT_PERSONA_ID", 0)),
        help="Persona ID used when creating new chat sessions (default: %(default)s)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the MCP server (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the MCP server (default: %(default)d)",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="HTTP path for the MCP server (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()

    config = OnyxConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        default_persona_id=args.persona_id,
    )

    if not config.api_key:
        logger.warning(
            "No ONYX_API_KEY provided. The Onyx deployment must allow unauthenticated access or the tool will fail."
        )

    mcp = build_mcp_server(config)
    mcp.run(transport="http", host=args.host, port=args.port, path=args.path)


if __name__ == "__main__":
    main()
