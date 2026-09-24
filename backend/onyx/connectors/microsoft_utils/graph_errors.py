"""Shared parsing for Microsoft Graph and MSAL failures."""

import json
import re
from collections.abc import Generator
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict

NO_ERROR_CODE = "<no code>"
_MSAL_STATUS_RE = re.compile(r"HTTP (?:status|Error): (\d{3})")


class MicrosoftGraphErrorDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: int | None
    code: str
    message: str


def _exception_chain(error: BaseException) -> Generator[BaseException, None, None]:
    current: BaseException | None = error
    while current is not None:
        yield current
        current = current.__cause__ or current.__context__


def is_msal_decode_error(error: BaseException) -> bool:
    return any(
        isinstance(wrapped, json.JSONDecodeError) for wrapped in _exception_chain(error)
    )


def msal_http_status(error: BaseException) -> int | None:
    for wrapped in _exception_chain(error):
        if match := _MSAL_STATUS_RE.search(str(wrapped)):
            return int(match.group(1))
    return None


def parse_msal_error(error: BaseException) -> MicrosoftGraphErrorDetails:
    return MicrosoftGraphErrorDetails(
        status=msal_http_status(error),
        code=type(error).__name__,
        message=str(error),
    )


def parse_graph_error(error: Exception) -> MicrosoftGraphErrorDetails:
    response = error.response if isinstance(error, requests.RequestException) else None
    if response is None:
        return MicrosoftGraphErrorDetails(
            status=None,
            code=type(error).__name__,
            message=str(error),
        )

    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return MicrosoftGraphErrorDetails(
            status=response.status_code,
            code=NO_ERROR_CODE,
            message=response.text[:500],
        )

    detail = payload.get("error")
    if isinstance(detail, dict):
        code = detail.get("code") or NO_ERROR_CODE
        message = detail.get("message") or response.text
    else:
        code = detail or NO_ERROR_CODE
        message = payload.get("error_description") or response.text
    return MicrosoftGraphErrorDetails(
        status=response.status_code,
        code=str(code),
        message=str(message)[:500],
    )
