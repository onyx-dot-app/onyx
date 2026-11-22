"""The error kind of a check that did not pass, and the sign-in policy: a
check that ``fails_when_unreachable`` FAILS on a form run when the source is
unreachable, and is INCOMPLETE on any other run."""

import time
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import draft_runs
from onyx.connectors.capability_checks.draft_runs import cache_draft_result
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckErrorKind,
    CredentialCapability,
    aggregate_capability_verdict,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)

_TIMEOUT_SECONDS = 0.2


class _RaisingCheck(CapabilityCheck):
    def __init__(self, error: Exception | None, fails_when_unreachable: bool) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="raising_check",
            display_name="Raising check",
            requires_connector_instance=False,
            timeout_seconds=_TIMEOUT_SECONDS,
            fails_when_unreachable=fails_when_unreachable,
        )
        self._error = error

    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        if self._error is None:
            time.sleep(_TIMEOUT_SECONDS * 5)
            return
        raise self._error


def _run(
    error: Exception | None, *, fails_when_unreachable: bool, form_run: bool
) -> CapabilityCheckResult:
    """``error`` None makes the check time out."""
    context = CapabilityCheckContext(source=DocumentSource.SLACK, credential_json={})
    (result,) = run_capability_checks(
        [_RaisingCheck(error, fails_when_unreachable)], context, form_run=form_run
    )
    return result


@pytest.mark.parametrize(
    ("error", "status", "kind"),
    [
        (
            CredentialExpiredError("Rejected."),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.REJECTED,
        ),
        (
            InsufficientPermissionsError("No scope."),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.PERMISSION,
        ),
        (
            ConnectorValidationError("No such space."),
            CapabilityCheckStatus.FAILED,
            CheckErrorKind.INVALID,
        ),
        (
            RateLimitedValidationError("Slow down."),
            CapabilityCheckStatus.INCOMPLETE,
            CheckErrorKind.RATE_LIMITED,
        ),
        (
            UnreachableValidationError("No route."),
            CapabilityCheckStatus.INCOMPLETE,
            CheckErrorKind.UNREACHABLE,
        ),
        (
            UnexpectedValidationError("HTTP 502."),
            CapabilityCheckStatus.INCOMPLETE,
            CheckErrorKind.UNEXPECTED,
        ),
        (None, CapabilityCheckStatus.INCOMPLETE, CheckErrorKind.TIMEOUT),
    ],
)
def test_error_kind_and_status(
    error: Exception | None, status: CapabilityCheckStatus, kind: CheckErrorKind
) -> None:
    result = _run(error, fails_when_unreachable=False, form_run=True)

    assert (result.status, result.error_kind) == (status, kind)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (UnreachableValidationError("No route."), CheckErrorKind.UNREACHABLE),
        (None, CheckErrorKind.TIMEOUT),
    ],
)
def test_a_sign_in_check_fails_on_an_unreachable_source_only_on_a_form_run(
    error: Exception | None, kind: CheckErrorKind
) -> None:
    on_form = _run(error, fails_when_unreachable=True, form_run=True)
    elsewhere = _run(error, fails_when_unreachable=True, form_run=False)

    assert (on_form.status, on_form.error_kind) == (CapabilityCheckStatus.FAILED, kind)
    assert (elsewhere.status, elsewhere.error_kind) == (
        CapabilityCheckStatus.INCOMPLETE,
        kind,
    )


@pytest.mark.parametrize(
    "error", [RateLimitedValidationError("Slow down."), UnexpectedValidationError()]
)
def test_a_sign_in_check_stays_incomplete_when_the_source_answers(
    error: Exception,
) -> None:
    """A rate limit or a server error means the source answered: the account
    may be fine."""
    result = _run(error, fails_when_unreachable=True, form_run=True)

    assert result.status == CapabilityCheckStatus.INCOMPLETE


def test_a_legacy_indeterminate_result_counts_as_incomplete() -> None:
    """Stored reports still hold INDETERMINATE."""
    legacy = CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id="legacy_check",
        display_name="Legacy check",
        required=True,
        status=CapabilityCheckStatus.INDETERMINATE,
    )

    assert (
        aggregate_capability_verdict(True, [legacy])
        == aggregate_capability_verdict(
            True,
            [legacy.model_copy(update={"status": CapabilityCheckStatus.INCOMPLETE})],
        )
        == CapabilityVerdict.INDETERMINATE
    )


def test_a_draft_run_caches_a_rejected_sign_in_but_not_an_unreachable_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable source may answer on the next run, so its FAILED sign-in
    is not reused."""
    cache: MagicMock = MagicMock()
    monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: cache)

    cache_draft_result(
        "unreachable",
        _run(
            UnreachableValidationError("No route."),
            fails_when_unreachable=True,
            form_run=True,
        ),
    )
    assert cache.set.call_count == 0

    cache_draft_result(
        "rejected",
        _run(
            CredentialExpiredError("Rejected."),
            fails_when_unreachable=True,
            form_run=True,
        ),
    )
    assert cache.set.call_count == 1
