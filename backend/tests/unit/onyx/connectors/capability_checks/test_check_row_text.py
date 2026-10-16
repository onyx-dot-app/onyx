"""A row's short line and description: the check error's own, else the
default of its kind, and the not-run line for a check a gate stopped."""

import time

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    RateLimitedValidationError,
)

_TIMEOUT_SECONDS = 0.2


class _Check(CapabilityCheck):
    def __init__(
        self,
        check_id: str,
        error: Exception | None = None,
        *,
        hangs: bool = False,
        depends_on: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=f"Run {check_id}",
            requires_connector_instance=False,
            timeout_seconds=_TIMEOUT_SECONDS,
            depends_on=depends_on,
        )
        self._error = error
        self._hangs = hangs

    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        if self._hangs:
            time.sleep(_TIMEOUT_SECONDS * 5)
        if self._error is not None:
            raise self._error


def _run(checks: list[CapabilityCheck]) -> dict[str, CapabilityCheckResult]:
    context = CapabilityCheckContext(source=DocumentSource.SLACK, credential_json={})
    return {
        result.check_id: result for result in run_capability_checks(checks, context)
    }


def test_a_check_error_gives_its_own_row_text() -> None:
    results = _run(
        [
            _Check(
                "sign_in",
                CredentialExpiredError(
                    "Rejected (HTTP 401).",
                    summary="Sign-in rejected",
                    description="The token was rejected. (HTTP 401)",
                ),
            )
        ]
    )

    assert results["sign_in"].summary == "Sign-in rejected"
    assert results["sign_in"].description == "The token was rejected. (HTTP 401)"
    assert results["sign_in"].message == "Rejected (HTTP 401)."


def test_a_kind_gives_default_row_text_and_a_failure_none() -> None:
    results = _run(
        [
            _Check("slow", hangs=True),
            _Check("rejected", CredentialExpiredError("Rejected.")),
            # Last: a rate limit stops the checks after it.
            _Check("limited", RateLimitedValidationError("Slow down.")),
        ]
    )

    assert results["slow"].summary == "Timed out"
    assert results["limited"].summary == "Rate limited"
    assert results["rejected"].summary is None


def test_a_not_run_row_shows_its_line() -> None:
    results = _run(
        [
            _Check("sign_in", CredentialExpiredError("Rejected.")),
            _Check("list", depends_on=("sign_in",)),
            _Check("content", depends_on=("list",)),
        ]
    )

    assert results["list"].summary == "Not run: Run sign_in failed"
    assert results["content"].summary == "Not run: Run sign_in failed"
