"""The one HTTP sender for the API integration tools (OpenAPI, GraphQL and
app action tools) and for the GraphQL introspection call of the
integration service."""

from email.message import Message
from enum import Enum
from typing import Any
from uuid import UUID

import requests
from pydantic import BaseModel, ConfigDict, JsonValue

from onyx.integrations.call_credentials import (
    credentials_near_expiry,
    mark_api_key_rejected,
    resolve_fresh_call_credentials,
)
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.models import CallCredentials
from onyx.llm.models import ToolResult
from onyx.server.security.models import OutboundSSRFParams, SSRFProtectionLevel
from onyx.server.security.store import get_security_settings
from onyx.tools.models import CustomToolCallSummary, CustomToolErrorInfo
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, ssrf_safe_request
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# (connect, read) seconds
TOOL_REQUEST_TIMEOUT: tuple[float, float] = (10, 120)
_READ_CHUNK_BYTES = 64 * 1024


def tool_request_ssrf_params() -> OutboundSSRFParams:
    """Cloud blocks every internal target. Self-hosted allows private hosts,
    allows loopback only at DISABLED, and always blocks link-local/metadata.

    Self-hosted allows private ranges at every level, VALIDATE_ALL included, so
    admins can call internal APIs. This is an accepted risk (ENG-4421)."""
    if MULTI_TENANT:
        return OutboundSSRFParams(
            allow_private_network=False,
            block_loopback_and_link_local=True,
            block_link_local_only=False,
        )
    ssrf_disabled = (
        get_security_settings().ssrf_protection_level == SSRFProtectionLevel.DISABLED
    )
    return OutboundSSRFParams(
        allow_private_network=True,
        block_loopback_and_link_local=not ssrf_disabled,
        block_link_local_only=ssrf_disabled,
    )


class ToolRequestFailure(str, Enum):
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
    REDIRECT = "redirect"


# The text of each failure but REDIRECT, which each tool words for its caller.
TOOL_REQUEST_FAILURE_MESSAGES: dict[ToolRequestFailure, str] = {
    ToolRequestFailure.BLOCKED: "The destination is not allowed.",
    ToolRequestFailure.TIMEOUT: "The server did not answer in time.",
    ToolRequestFailure.UNREACHABLE: "The connection to the server failed.",
}


class ToolRequestError(Exception):
    """The request did not give a response that the tool can use."""

    def __init__(
        self, failure: ToolRequestFailure, status_code: int | None = None
    ) -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.status_code = status_code

    @property
    def is_unreachable(self) -> bool:
        return self.failure in (
            ToolRequestFailure.TIMEOUT,
            ToolRequestFailure.UNREACHABLE,
        )


class ToolResponse(BaseModel):
    """A response whose body was read up to the limit of the call."""

    model_config = ConfigDict(frozen=True)

    status_code: int
    content_type: str
    body: bytes
    # The body is longer than the limit; ``body`` holds the first part.
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        """The body decoded with the charset of the response, else UTF-8."""
        header = Message()
        header["Content-Type"] = self.content_type
        try:
            return self.body.decode(
                header.get_content_charset() or "utf-8", errors="replace"
            )
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def failed_tool_result(
    *,
    tool_name: str,
    integration_id: int,
    message: str,
    status_code: int | None = None,
    is_unreachable: bool = False,
    is_auth_error: bool = False,
) -> ToolResult:
    """The error result of an API integration tool call."""
    return ToolResult(
        content=message,
        is_error=True,
        details=CustomToolCallSummary(
            tool_name=tool_name,
            integration_id=integration_id,
            response_type="text",
            tool_result=None,
            error=CustomToolErrorInfo(
                status_code=status_code,
                message=message,
                is_unreachable=is_unreachable,
                is_auth_error=is_auth_error,
            ),
        ),
    )


def send_tool_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    max_response_bytes: int | None = None,
    json_body: JsonValue | None = None,
) -> ToolResponse:
    """Send one request with the SSRF checks of a custom tool. A redirect is
    refused, so a credential header never goes to a second host. Raises
    ``ToolRequestError``."""
    params = tool_request_ssrf_params()
    body: dict[str, Any] = {} if json_body is None else {"json": json_body}
    try:
        response = ssrf_safe_request(
            url,
            method=method,
            headers=headers,
            timeout=TOOL_REQUEST_TIMEOUT,
            allow_private_network=params.allow_private_network,
            block_loopback_and_link_local=params.block_loopback_and_link_local,
            block_link_local_only=params.block_link_local_only,
            stream=True,
            **body,
        )
    except (SSRFException, ValueError) as e:
        raise ToolRequestError(ToolRequestFailure.BLOCKED) from e
    except requests.exceptions.Timeout as e:
        raise ToolRequestError(ToolRequestFailure.TIMEOUT) from e
    except requests.exceptions.ConnectionError as e:
        raise ToolRequestError(ToolRequestFailure.UNREACHABLE) from e
    try:
        if response.is_redirect:
            raise ToolRequestError(ToolRequestFailure.REDIRECT, response.status_code)
        chunks: list[bytes] = []
        size = 0
        truncated = False
        for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
            room = (
                len(chunk) if max_response_bytes is None else max_response_bytes - size
            )
            if len(chunk) > room:
                chunks.append(chunk[:room])
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
        return ToolResponse(
            status_code=response.status_code,
            content_type=response.headers.get("Content-Type", ""),
            body=b"".join(chunks),
            truncated=truncated,
        )
    except requests.exceptions.Timeout as e:
        raise ToolRequestError(ToolRequestFailure.TIMEOUT) from e
    except requests.exceptions.RequestException as e:
        raise ToolRequestError(ToolRequestFailure.UNREACHABLE) from e
    finally:
        response.close()


def fresh_call_credentials(
    credentials: CallCredentials, acting_user_id: UUID | None
) -> CallCredentials | ConnectionProblem:
    """The credential to send: the given one, or the one resolved again when
    its token expires soon."""
    if not credentials_near_expiry(credentials):
        return credentials
    return resolve_fresh_call_credentials(credentials.integration_id, acting_user_id)


def note_rejected_credential(
    response: ToolResponse, credentials: CallCredentials
) -> None:
    """A 401 on an API key marks its connection Needs reconnect."""
    if response.status_code != 401:
        return
    try:
        mark_api_key_rejected(credentials)
    except Exception:
        logger.exception("Could not record the rejected credential")
