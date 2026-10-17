"""Timeouts: a ``TimedOutValidationError`` has the timeout kind and the
sign-in policy of an unreachable source, the hang guard uses a check's own
timeout text, and an error detail survives a cycle in the cause chain."""

import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckRowText,
    CredentialCapability,
    check_error_detail,
    sign_in_timeout_text,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import (
    _hang_guard_row,
    run_capability_checks,
)
from onyx.connectors.exceptions import (
    SourceApiError,
    TimedOutValidationError,
    UnreachableValidationError,
)
from onyx.utils.threadpool_concurrency import run_with_timeout

_TIMEOUT_SECONDS = 0.2
_OWN_TEXT = CheckRowText(summary="Sign-in timed out", description="Slow.\nRe-run.")


class _SlowCheck(CapabilityCheck):
    """Raises ``error``, or sleeps past its hang guard when it is None."""

    def __init__(
        self,
        error: Exception | None = None,
        *,
        fails_when_unreachable: bool = False,
        timeout_text: CheckRowText | None = None,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="slow_check",
            display_name="Slow check",
            requires_connector_instance=False,
            timeout_seconds=_TIMEOUT_SECONDS,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=timeout_text,
        )
        self._error = error

    def run(self, context: CapabilityCheckContext) -> None:  # noqa: ARG002
        if self._error is None:
            time.sleep(_TIMEOUT_SECONDS * 5)
            return
        raise self._error


def _run(check: CapabilityCheck, *, form_run: bool = False) -> CapabilityCheckResult:
    context = CapabilityCheckContext(source=DocumentSource.SLACK, credential_json={})
    (result,) = run_capability_checks([check], context, form_run=form_run)
    return result


@pytest.mark.parametrize(
    ("fails_when_unreachable", "form_run", "status"),
    [
        (True, True, CapabilityCheckStatus.FAILED),
        (True, False, CapabilityCheckStatus.INCOMPLETE),
        (False, True, CapabilityCheckStatus.INCOMPLETE),
    ],
)
def test_a_timed_out_error_follows_the_unreachable_policy(
    fails_when_unreachable: bool, form_run: bool, status: CapabilityCheckStatus
) -> None:
    check = _SlowCheck(
        TimedOutValidationError("Slow."), fails_when_unreachable=fails_when_unreachable
    )

    result = _run(check, form_run=form_run)

    assert (result.status, result.error_kind) == (status, CheckErrorKind.TIMEOUT)
    assert result.summary == "Timed out"
    assert result.error_detail is not None
    assert result.error_detail.stack_trace is not None


def test_a_timed_out_error_is_still_an_unreachable_error() -> None:
    assert isinstance(TimedOutValidationError(), UnreachableValidationError)


def test_the_hang_guard_uses_the_check_s_timeout_text() -> None:
    result = _run(
        _SlowCheck(fails_when_unreachable=True, timeout_text=_OWN_TEXT), form_run=True
    )

    assert result.status == CapabilityCheckStatus.FAILED
    assert result.error_kind == CheckErrorKind.TIMEOUT
    assert (result.summary, result.description) == (
        _OWN_TEXT.summary,
        _OWN_TEXT.description,
    )


def test_the_hang_guard_keeps_the_default_text_without_one() -> None:
    result = _run(_SlowCheck())

    assert result.summary == "Timed out"
    assert result.description is not None
    assert result.description.startswith("The check did not finish in time.")


def test_an_error_s_own_text_wins_over_the_timeout_text() -> None:
    error = TimedOutValidationError("Slow.", summary="Own line", description="Own.")

    result = _run(_SlowCheck(error, timeout_text=_OWN_TEXT))

    assert (result.summary, result.description) == ("Own line", "Own.")


@pytest.mark.parametrize(
    ("seconds", "words"),
    [(600, "10 minutes"), (60, "1 minute"), (90, "90 seconds"), (1, "1 second")],
)
def test_the_timeout_text_names_the_guard_s_time_limit(
    seconds: float, words: str
) -> None:
    check = _SlowCheck(
        timeout_text=CheckRowText(
            summary="Timed out", description="Stopped after {time_limit}."
        )
    )

    row = _hang_guard_row(check, seconds)

    assert row is not None
    assert row.description == f"Stopped after {words}."


_SIGN_IN_CHECKS: dict[DocumentSource, tuple[str, set[str]]] = {
    DocumentSource.CONFLUENCE: (
        "Confluence",
        {"confluence_auth", "confluence_scoped_token_auth"},
    ),
    DocumentSource.JIRA: ("Jira", {"jira_auth", "jira_scoped_token_auth"}),
    DocumentSource.GOOGLE_DRIVE: ("Google Drive", {"google_drive_auth"}),
    DocumentSource.GITHUB: ("GitHub", {"github_auth"}),
    DocumentSource.LINEAR: ("Linear", {"linear_token"}),
    DocumentSource.SLACK: ("Slack", {"slack_token_auth"}),
    DocumentSource.NOTION: ("Notion", {"notion_auth"}),
    DocumentSource.HUBSPOT: ("HubSpot", {"hubspot_token"}),
    DocumentSource.SHAREPOINT: ("SharePoint", {"sharepoint_token_auth"}),
    DocumentSource.ONEDRIVE: ("OneDrive", {"onedrive_token_auth"}),
    DocumentSource.OUTLOOK: ("Outlook", {"outlook_token_auth"}),
}


@pytest.mark.parametrize("source", list(_SIGN_IN_CHECKS))
def test_each_check_has_the_design_s_timeout_text(source: DocumentSource) -> None:
    """Sign-in rows have their own line; the other rows share the source's."""
    name, sign_in_ids = _SIGN_IN_CHECKS[source]
    checks = get_capability_checks(source)

    for check in checks:
        if check.check_id in sign_in_ids:
            assert check.timeout_text == sign_in_timeout_text(name), check.check_id
        else:
            assert check.timeout_text is not None, check.check_id
            assert check.timeout_text.summary == "Timed out", check.check_id
    assert sign_in_ids <= {check.check_id for check in checks}


def test_an_error_detail_survives_a_cycle_in_the_cause_chain() -> None:
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first

    detail = run_with_timeout(
        5, check_error_detail, first, CheckErrorKind.UNEXPECTED, []
    )

    assert detail is not None
    assert detail.status_code is None
    assert detail.stack_trace is not None


def test_an_error_detail_finds_the_response_before_a_cycle() -> None:
    api_error = SourceApiError(
        "HTTP 500", status_code=500, method="GET", url="https://api.example.com/x"
    )
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = api_error
    api_error.__cause__ = wrapper

    detail = run_with_timeout(
        5, check_error_detail, wrapper, CheckErrorKind.UNEXPECTED, []
    )

    assert detail is not None
    assert (detail.status_code, detail.request) == (500, "GET api.example.com/x")
