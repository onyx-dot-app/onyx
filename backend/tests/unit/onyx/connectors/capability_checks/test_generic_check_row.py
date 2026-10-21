"""The generic row of a source without named checks: "Test connection",
"Connected" on a pass, and a typed line and description for each failure of
the legacy settings probe, in a draft run and in a recorded outcome alike."""

from unittest.mock import MagicMock

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CredentialCapability,
)
from onyx.connectors.capability_checks.recorder import _synthesize_results
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import BaseConnector

_SOURCE = DocumentSource.BOX


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response._content = b'{"message": "denied"}'
    response.url = "https://api.example.com/2.0/folders/0?token=secret"
    return requests.HTTPError(f"{status} error", response=response)


def _run(error: Exception | None, form_run: bool = False) -> CapabilityCheckResult:
    connector = MagicMock(spec=BaseConnector)
    connector.validate_connector_settings.side_effect = error
    checks = [
        check
        for check in get_capability_checks(_SOURCE)
        if check.capability == CredentialCapability.INDEXING
    ]
    (result,) = run_capability_checks(
        checks,
        CapabilityCheckContext(source=_SOURCE, credential_json={}, connector=connector),
        form_run=form_run,
    )
    return result


def test_pass_shows_connected() -> None:
    # Under test.
    result = _run(None)

    # Postcondition.
    assert result.display_name == "Test connection"
    assert result.status == CapabilityCheckStatus.PASSED
    assert result.summary == "Connected"


@pytest.mark.parametrize(
    ("error", "status", "kind", "error_type", "summary"),
    [
        (
            _http_error(401),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.REJECTED,
            "CredentialInvalidError",
            "Sign-in rejected",
        ),
        (
            CredentialExpiredError("token expired"),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.REJECTED,
            "CredentialExpiredError",
            "Sign-in rejected",
        ),
        (
            _http_error(403),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.PERMISSION,
            "InsufficientPermissionsError",
            "No permission for the connector",
        ),
        (
            InsufficientPermissionsError("missing scope"),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.PERMISSION,
            "InsufficientPermissionsError",
            "No permission for the connector",
        ),
        (
            SourceApiError("no folder", status_code=404),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.INVALID,
            "ConnectorValidationError",
            "Not found at the source",
        ),
        (
            ConnectorValidationError("Folder ID must be numeric"),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.INVALID,
            "ConnectorValidationError",
            "Settings not accepted",
        ),
        (
            _http_error(429),
            CapabilityCheckStatus.INCOMPLETE,
            CheckErrorKind.RATE_LIMITED,
            "RateLimitedValidationError",
            "Rate limited by the source",
        ),
        (
            requests.ConnectionError("connection refused"),
            CapabilityCheckStatus.INCOMPLETE,
            CheckErrorKind.UNREACHABLE,
            "UnreachableValidationError",
            "Cannot reach the source",
        ),
        (
            RuntimeError("boom"),
            CapabilityCheckStatus.INCOMPLETE,
            CheckErrorKind.UNEXPECTED,
            "UnexpectedValidationError",
            "Unexpected response from the source",
        ),
    ],
)
def test_failure_gets_its_typed_row(
    error: Exception,
    status: CapabilityCheckStatus,
    kind: CheckErrorKind,
    error_type: str,
    summary: str,
) -> None:
    # Under test.
    result = _run(error)

    # Postcondition.
    assert result.status == status
    assert result.error_kind == kind
    assert result.error_type == error_type
    assert result.summary == summary
    assert result.description is not None
    assert len(result.description.splitlines()) <= 3
    # The probe's own text stays the message, for Error Details.
    assert result.message == str(error)


def test_description_names_the_http_status() -> None:
    # Under test.
    result = _run(_http_error(401))

    # Postcondition.
    assert result.description is not None
    assert result.description.splitlines()[0].endswith("(HTTP 401)")
    assert result.error_detail is not None
    assert result.error_detail.status_code == 401
    assert result.error_detail.request == "api.example.com/2.0/folders/0"


def test_a_narrowed_error_keeps_its_stack_trace() -> None:
    """The row text of a legacy probe's error is inferred, so support can still
    read the original stack trace, even for a known kind such as rejected."""
    try:
        raise ConnectorValidationError("settings failed") from _http_error(401)
    except ConnectorValidationError as e:
        error = e

    # Under test.
    result = _run(error)

    # Postcondition.
    assert result.error_kind == CheckErrorKind.REJECTED
    assert result.error_detail is not None
    assert result.error_detail.stack_trace is not None
    assert "settings failed" in result.error_detail.stack_trace
    assert "token=secret" not in result.error_detail.stack_trace


def test_error_with_its_own_row_keeps_it() -> None:
    # Precondition.
    error = UnexpectedValidationError(
        "Box API is down", summary="Box is down", description="Try later."
    )

    # Under test.
    result = _run(error)

    # Postcondition.
    assert result.summary == "Box is down"
    assert result.description == "Try later."


def _wrapped(error: Exception, cause: Exception) -> Exception:
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("error", "status", "error_type", "summary"),
    [
        # A settings probe that wraps a 429 still rejects the settings, as
        # blocking validation does with the same error.
        (
            _wrapped(ConnectorValidationError("bad settings"), _http_error(429)),
            CapabilityCheckStatus.FAILED,
            "ConnectorValidationError",
            "Settings not accepted",
        ),
        # A status narrows a typed error to a subclass of its own class.
        (
            _wrapped(ConnectorValidationError("bad token"), _http_error(401)),
            CapabilityCheckStatus.FAILED,
            "CredentialInvalidError",
            "Sign-in rejected",
        ),
        (
            _wrapped(UnexpectedValidationError("busy"), _http_error(429)),
            CapabilityCheckStatus.INCOMPLETE,
            "RateLimitedValidationError",
            "Rate limited by the source",
        ),
    ],
)
def test_typed_error_keeps_its_class_over_its_http_status(
    error: Exception, status: CapabilityCheckStatus, error_type: str, summary: str
) -> None:
    # Under test.
    result = _run(error)

    # Postcondition.
    assert result.status == status
    assert result.error_type == error_type
    assert result.summary == summary


def test_unreachable_source_fails_on_a_form_run_only() -> None:
    # Under test and postcondition.
    error = requests.ConnectionError("connection refused")
    assert _run(error, form_run=True).status == CapabilityCheckStatus.FAILED
    assert _run(error).status == CapabilityCheckStatus.INCOMPLETE


def test_rate_limit_from_a_typed_error() -> None:
    # Under test.
    result = _run(RateLimitedValidationError())

    # Postcondition.
    assert result.error_kind == CheckErrorKind.RATE_LIMITED
    assert result.summary == "Rate limited by the source"


def test_recorded_outcome_is_the_generic_row() -> None:
    # Under test.
    passed = _synthesize_results(_SOURCE, {CredentialCapability.INDEXING}, None, False)
    failed = _synthesize_results(
        _SOURCE, {CredentialCapability.INDEXING}, _http_error(403), False
    )

    # Postcondition.
    (passed_row,) = passed
    assert passed_row.display_name == "Test connection"
    assert passed_row.summary == "Connected"
    (failed_row,) = failed
    assert failed_row.status == CapabilityCheckStatus.FAILED
    assert failed_row.error_kind == CheckErrorKind.PERMISSION
    assert failed_row.summary == "No permission for the connector"
    # The original class, for support.
    assert failed_row.error_type == "HTTPError"


def test_recorded_pass_without_a_settings_probe_has_no_row() -> None:
    """A source whose connector keeps the no-op probe tested nothing, so its
    pass records no row; a failure, e.g. at construction, still does."""
    # Under test and postcondition.
    indexing = {CredentialCapability.INDEXING}
    assert _synthesize_results(DocumentSource.GITLAB, indexing, None, False) == []
    (row,) = _synthesize_results(
        DocumentSource.GITLAB, indexing, RuntimeError("bad config"), False
    )
    assert row.status == CapabilityCheckStatus.INCOMPLETE
