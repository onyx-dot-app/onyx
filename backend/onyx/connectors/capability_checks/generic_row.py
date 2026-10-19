"""The generic row: what a source without named checks shows for its legacy
``validate_connector_settings`` probe. The fallback check and the
blocking-validation recorder both build it here, so a draft run and a stored
report show the same row.

Import-light, like the recorder: no registry, runner or factory imports.
"""

import requests

from onyx.connectors.capability_checks.models import CheckRowText
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    UnexpectedValidationError,
    UnreachableValidationError,
    ValidationError,
)

GENERIC_CHECK_NAME = "Test connection"
GENERIC_PASS_LINE = "Connected"

_UNAUTHORIZED = 401
_FORBIDDEN = 403
_NOT_FOUND = 404
_TOO_MANY_REQUESTS = 429
# No answer from the source: the connection failed or timed out.
_UNREACHABLE_ERRORS: tuple[type[Exception], ...] = (
    requests.ConnectionError,
    requests.Timeout,
    ConnectionError,
    TimeoutError,
)


_REJECTED_ROW = CheckRowText(
    summary="Sign-in rejected",
    description=(
        "The source rejected the account's credential.\n"
        "Update the credential in the account, then re-run."
    ),
)
_DENIED_ROW = CheckRowText(
    summary="No permission for the connector",
    description=(
        "The credential signs in, but lacks a permission the connector needs.\n"
        "Give the account that permission, then re-run."
    ),
)
_NOT_FOUND_ROW = CheckRowText(
    summary="Not found at the source",
    description=(
        "The source found nothing at the configured address or ID.\n"
        "Correct the connector settings, then re-run."
    ),
)
_SETTINGS_ROW = CheckRowText(
    summary="Settings not accepted",
    description=(
        "The source did not accept the connector settings.\n"
        "Read the error details, then correct the settings."
    ),
)
_RATE_LIMITED_ROW = CheckRowText(
    summary="Rate limited by the source",
    description=(
        "The source limited the number of requests.\nWait a minute, then re-run."
    ),
)
_UNREACHABLE_ROW = CheckRowText(
    summary="Cannot reach the source",
    description=(
        "Onyx could not connect to the source.\n"
        "Check the address in the settings, then re-run."
    ),
)
_UNEXPECTED_ROW = CheckRowText(
    summary="Unexpected response from the source",
    description=(
        "The source answered in a way the check does not know.\n"
        "Re-run the checks. If it repeats, share the error details with support."
    ),
)


def _http_status(error: BaseException) -> int | None:
    """The HTTP status of the first error in the chain that carries one."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, SourceApiError):
            return current.status_code
        if isinstance(current, requests.HTTPError) and current.response is not None:
            return current.response.status_code
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _with_status(row: CheckRowText, status: int | None) -> CheckRowText:
    """Adds the HTTP status to the row's first description line."""
    if status is None:
        return row
    first, newline, rest = row.description.partition("\n")
    return CheckRowText(
        summary=row.summary, description=f"{first} (HTTP {status}){newline}{rest}"
    )


def _typed(
    error: Exception, status: int | None
) -> tuple[type[ValidationError], CheckRowText]:
    """The error's class and row. A typed error keeps its class; an untyped
    one gets its class from its HTTP status, as the named checks map them."""
    if isinstance(error, RateLimitedValidationError) or status == _TOO_MANY_REQUESTS:
        return RateLimitedValidationError, _RATE_LIMITED_ROW
    if isinstance(error, (UnreachableValidationError, *_UNREACHABLE_ERRORS)):
        return UnreachableValidationError, _UNREACHABLE_ROW
    if isinstance(error, CredentialExpiredError):
        return CredentialExpiredError, _REJECTED_ROW
    if isinstance(error, CredentialInvalidError):
        return CredentialInvalidError, _REJECTED_ROW
    if isinstance(error, InsufficientPermissionsError):
        return InsufficientPermissionsError, _DENIED_ROW
    if status == _UNAUTHORIZED:
        return CredentialInvalidError, _REJECTED_ROW
    if status == _FORBIDDEN:
        return InsufficientPermissionsError, _DENIED_ROW
    if status == _NOT_FOUND:
        return ConnectorValidationError, _NOT_FOUND_ROW
    if isinstance(error, ConnectorValidationError):
        return ConnectorValidationError, _SETTINGS_ROW
    return UnexpectedValidationError, _UNEXPECTED_ROW


def generic_row_error(error: Exception) -> ValidationError:
    """The validation error the generic row shows for a legacy probe's
    error, with its line and description. ``message`` keeps the probe's own
    text for Error Details. An error that already gives its row is kept."""
    if isinstance(error, ValidationError) and error.summary is not None:
        return error
    status = _http_status(error)
    error_class, row = _typed(error, status)
    row = _with_status(row, status)
    return error_class(str(error), summary=row.summary, description=row.description)
