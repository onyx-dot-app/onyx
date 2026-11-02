"""The workspace switch for capability check findings, and what responses
show of stored results.

With ``allow_connector_check_findings`` off, no finding is stored or cached,
and responses hide findings stored before the switch was turned off.
"""

from collections.abc import Iterable
from typing import Protocol

from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CheckFinding,
)
from onyx.server.security.store import get_security_settings


class _HasFindings(Protocol):
    findings: list[CheckFinding]


def check_findings_enabled() -> bool:
    return get_security_settings().allow_connector_check_findings


def hide_findings_if_disabled(items: Iterable[_HasFindings]) -> None:
    """Clears the findings of response objects built from stored data."""
    if check_findings_enabled():
        return
    for item in items:
        item.findings = []


def shown_check_results(
    results: Iterable[CapabilityCheckResult],
) -> list[CapabilityCheckResult]:
    """The stored results a response lists: checks that do not apply to the
    scope are left out, and findings follow the workspace switch. The stored
    report, its verdicts and the indexing hold keep every result."""
    shown = [result for result in results if result.applicable]
    hide_findings_if_disabled(shown)
    return shown
