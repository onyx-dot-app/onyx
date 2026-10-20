"""A row's short line and description: the check error's own, else the
default of its kind, and the not-run line for a check a gate stopped."""

import ast
import time
from pathlib import Path

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InconclusiveValidationError,
    NothingToCheckError,
    RateLimitedValidationError,
)

_TIMEOUT_SECONDS = 0.2
_BACKEND_ROOT = Path(__file__).parents[5]
_MAX_DESCRIPTION_LINES = 3
# Calls that take a row description without a ``summary`` keyword.
_ROW_TEXT_CALLS = frozenset({"CheckRowText", "CheckOutput"})


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


def test_an_inconclusive_sample_is_incomplete_without_a_stack_trace() -> None:
    result = _run(
        [
            _Check(
                "comments",
                InconclusiveValidationError(
                    "No comments.", summary="No comments found to test"
                ),
            )
        ]
    )["comments"]

    assert result.status == CapabilityCheckStatus.INCOMPLETE
    assert result.error_kind == CheckErrorKind.INCONCLUSIVE
    assert result.summary == "No comments found to test"
    assert result.error_detail is None


def test_nothing_in_scope_is_a_skipped_row_and_stops_its_dependents() -> None:
    results = _run(
        [
            _Check(
                "emails",
                NothingToCheckError(
                    "Groups only.",
                    summary="No users in space permissions",
                    description="The space grants access only to groups.",
                ),
            ),
            _Check("member_emails", depends_on=("emails",)),
        ]
    )

    emails = results["emails"]
    assert emails.status == CapabilityCheckStatus.SKIPPED
    assert emails.applicable
    assert emails.not_run_reason == CheckNotRunReason.NOTHING_IN_SCOPE
    assert emails.summary == "No users in space permissions"
    dependent = results["member_emails"]
    assert dependent.not_run_reason == CheckNotRunReason.DEPENDENCY_SKIPPED
    assert dependent.summary == "Not run: Run emails found nothing to test"


def _string_values(tree: ast.Module) -> dict[str, list[ast.expr]]:
    """Each name assigned in the file, with every value assigned to it."""
    values: dict[str, list[ast.expr]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                values.setdefault(target.id, []).append(value)
    return values


def _line_breaks(
    node: ast.expr, values: dict[str, list[ast.expr]], seen: frozenset[str]
) -> int:
    """The most line breaks the text of ``node`` can hold, as far as the file
    shows it: calls and attributes count as one line."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.count("\n")
    if isinstance(node, ast.JoinedStr):
        return sum(_line_breaks(value, values, seen) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        return _line_breaks(node.value, values, seen)
    if isinstance(node, ast.BinOp):
        return _line_breaks(node.left, values, seen) + _line_breaks(
            node.right, values, seen
        )
    if isinstance(node, ast.IfExp):
        return max(
            _line_breaks(node.body, values, seen),
            _line_breaks(node.orelse, values, seen),
        )
    if isinstance(node, ast.Name) and node.id not in seen:
        return max(
            (
                _line_breaks(value, values, seen | {node.id})
                for value in values.get(node.id, [])
            ),
            default=0,
        )
    return 0


def _long_descriptions(source: str) -> list[int]:
    """The lines of row-text calls whose description can pass the limit."""
    tree = ast.parse(source)
    values = _string_values(tree)
    long: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        description = keywords.get("description")
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if description is None or (
            "summary" not in keywords and name not in _ROW_TEXT_CALLS
        ):
            continue
        if _line_breaks(description, values, frozenset()) >= _MAX_DESCRIPTION_LINES:
            long.append(node.lineno)
    return long


def test_the_line_count_reads_names_and_branches() -> None:
    source = (
        'NEED = "Two\\nlines"\n'
        'CheckRowText(summary="s", description=f"One\\n{NEED}\\nFour")\n'
        'CheckOutput(description="a" if x else "b\\nc\\nd\\ne")\n'
        'CheckRowText(summary="s", description="One\\nTwo\\nThree")\n'
    )

    assert _long_descriptions(source) == [2, 3]


def test_every_row_description_has_at_most_three_lines() -> None:
    paths = sorted(
        {
            *(_BACKEND_ROOT / "onyx" / "connectors").rglob("*.py"),
            *(_BACKEND_ROOT / "ee" / "onyx").rglob("capability_checks*.py"),
        }
    )
    long = {
        str(path.relative_to(_BACKEND_ROOT)): lines
        for path in paths
        if (lines := _long_descriptions(path.read_text()))
    }

    assert long == {}
