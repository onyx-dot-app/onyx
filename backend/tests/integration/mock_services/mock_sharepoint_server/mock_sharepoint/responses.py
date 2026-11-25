"""Responses in the shapes Microsoft Graph, SharePoint REST and Entra use."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MockResponse(BaseModel):
    status: int
    body: bytes = b""
    headers: dict[str, str] = Field(default_factory=dict)
    # The drive item whose bytes this response served, for the stats.
    downloaded_item_id: str | None = None
    # Set on an RU rejection.
    throttled: bool = False


def json_response(
    status: int, payload: Any, headers: dict[str, str] | None = None
) -> MockResponse:
    return MockResponse(
        status=status,
        body=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )


def graph_error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> MockResponse:
    request_id = str(uuid.uuid4())
    return json_response(
        status,
        {
            "error": {
                "code": code,
                "message": message,
                "innerError": {
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    "request-id": request_id,
                    "client-request-id": request_id,
                },
            }
        },
        headers,
    )


def item_not_found() -> MockResponse:
    return graph_error(404, "itemNotFound", "The resource could not be found.")


def invalid_request(message: str) -> MockResponse:
    return graph_error(400, "invalidRequest", message)


def unauthenticated(message: str = "Access token is empty.") -> MockResponse:
    return graph_error(401, "InvalidAuthenticationToken", message)


def rest_error(status: int, code: str, message: str) -> MockResponse:
    """SharePoint REST's verbose OData error."""
    return json_response(
        status,
        {"error": {"code": code, "message": {"lang": "en-US", "value": message}}},
    )


def rest_not_found(message: str = "File Not Found.") -> MockResponse:
    return rest_error(404, "-2130575338, Microsoft.SharePoint.SPException", message)


def oauth_error(status: int, error: str, description: str) -> MockResponse:
    return json_response(
        status,
        {
            "error": error,
            "error_description": description,
            "error_codes": [],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        },
    )
