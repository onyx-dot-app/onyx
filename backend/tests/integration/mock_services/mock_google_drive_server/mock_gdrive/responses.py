"""Responses in the shapes Google's APIs use, errors included."""

import json
from typing import Any

from pydantic import BaseModel, Field


class MockResponse(BaseModel):
    status: int
    body: bytes = b""
    headers: dict[str, str] = Field(default_factory=dict)
    # The content file this response served, for the throughput stats.
    content_file_id: str | None = None
    # Set on a quota rejection.
    rate_limited: bool = False


def json_response(
    status: int, payload: Any, headers: dict[str, str] | None = None
) -> MockResponse:
    return MockResponse(
        status=status,
        body=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"content-type": "application/json; charset=UTF-8", **(headers or {})},
    )


def google_error(
    status: int,
    message: str,
    reason: str,
    *,
    domain: str = "global",
    location: str | None = None,
    api_status: str | None = None,
    headers: dict[str, str] | None = None,
) -> MockResponse:
    """The error body of the Drive and Admin SDK APIs. Client libraries read
    the reason from `error.errors[].reason`."""
    detail: dict[str, str] = {"message": message, "domain": domain, "reason": reason}
    if location:
        detail["location"] = location
        detail["locationType"] = "parameter"
    error: dict[str, Any] = {"code": status, "message": message, "errors": [detail]}
    if api_status:
        error["status"] = api_status
    return json_response(status, {"error": error}, headers)


def rpc_error(status: int, message: str, api_status: str) -> MockResponse:
    """The error body of the Docs API."""
    return json_response(
        status, {"error": {"code": status, "message": message, "status": api_status}}
    )


def bad_request(message: str, location: str | None = None) -> MockResponse:
    return google_error(
        400, message, "invalid" if location else "badRequest", location=location
    )


def file_not_found(file_id: str) -> MockResponse:
    return google_error(
        404, f"File not found: {file_id}.", "notFound", location="fileId"
    )


def drive_not_found(drive_id: str) -> MockResponse:
    return google_error(
        404, f"Shared drive not found: {drive_id}", "notFound", location="driveId"
    )


def directory_forbidden() -> MockResponse:
    return google_error(403, "Not Authorized to access this resource/api", "forbidden")


def insufficient_scopes() -> MockResponse:
    return google_error(
        403,
        "Request had insufficient authentication scopes.",
        "insufficientPermissions",
        api_status="PERMISSION_DENIED",
    )


def unauthenticated() -> MockResponse:
    return google_error(
        401,
        "Request had invalid authentication credentials. Expected OAuth 2 access "
        "token, login cookie or other valid authentication credential.",
        "authError",
        location="Authorization",
        api_status="UNAUTHENTICATED",
    )


def oauth_error(status: int, error: str, description: str) -> MockResponse:
    """The error body of the OAuth token endpoint."""
    return json_response(status, {"error": error, "error_description": description})
