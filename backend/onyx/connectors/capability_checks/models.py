import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.source_operations import SourceOperations
from onyx.db.enums import CapabilityCheckTrigger


class CapabilityCheckStatus(str, Enum):
    PASSED = "passed"
    # A ``ConnectorValidationError``-family failure: real and actionable.
    FAILED = "failed"
    # Transient or unknown failure (``UnexpectedValidationError`` or any
    # unrecognized exception). Mirrors the contract that such errors must never
    # be treated as proof the credential is broken.
    INDETERMINATE = "indeterminate"
    # The check needs state (connector instance or config) that was not
    # supplied.
    SKIPPED = "skipped"


class CapabilityVerdict(str, Enum):
    PASSED = "passed"
    # Only non-required checks failed: the capability works with caveats.
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    SKIPPED = "skipped"
    # The source does not have this capability (e.g. no group sync for Slack).
    NOT_APPLICABLE = "not_applicable"


class CapabilityCheckContext(BaseModel):
    """Inputs available to a capability check at run time.

    ``connector`` and ``connector_specific_config`` are None for config-less
    credential-time runs; the runner skips checks that declare a requirement on
    them. ``instantiation_error`` is set when connector construction failed for
    a supplied config; the runner surfaces it on instance-requiring checks
    instead of skipping them.

    ``source_operations`` is the gateway migrated checks compose; it is None for
    sources without one. ``connector`` serves the fallback path only: migrated
    checks need no connector instance.
    """

    # ``BaseConnector`` and ``SourceOperations`` are not pydantic types;
    # validate by isinstance.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    credential_json: dict[str, Any]
    connector: BaseConnector | None = None
    connector_specific_config: dict[str, Any] | None = None
    instantiation_error: Exception | None = None
    source_operations: SourceOperations | None = None


class CapabilityCheck(ABC):
    """
    A named probe of one permission/capability assumption a connector makes.

    Concrete checks pass their metadata to ``__init__`` and implement ``run``,
    which raises a ``ValidationError``-family exception on failure and returns
    nothing on success; the runner maps exceptions to statuses.
    """

    def __init__(
        self,
        *,
        capability: CredentialCapability,
        check_id: str,
        display_name: str,
        required: bool = True,
        requires_connector_instance: bool = True,
        requires_connector_config: bool = False,
        timeout_seconds: float | None = None,
        is_fallback: bool = False,
        remediation: str | None = None,
        docs_link: str | None = None,
    ) -> None:
        self.capability = capability
        self.check_id = check_id
        self.display_name = display_name
        # Required checks gate the capability verdict; non-required checks only
        # downgrade PASSED to PASSED_WITH_WARNINGS (partial capability).
        self.required = required
        self.requires_connector_instance = requires_connector_instance
        self.requires_connector_config = requires_connector_config
        # Per-check hang guard in seconds; None falls back to the
        # ``CAPABILITY_CHECK_TIMEOUT_SECONDS`` default. Timing out maps to
        # INDETERMINATE, never FAILED.
        self.timeout_seconds = timeout_seconds
        # True for synthesized wrappers around the legacy validation blobs
        # (``validate_connector_settings`` / ``validate_perm_sync``) rather than
        # named per-permission probes.
        self.is_fallback = is_fallback
        self.remediation = remediation
        self.docs_link = docs_link

    @abstractmethod
    def run(self, context: CapabilityCheckContext) -> None:
        """Probes the capability; raises on failure, returns on success."""


class CapabilityCheckResult(BaseModel):
    capability: CredentialCapability
    check_id: str
    display_name: str
    required: bool
    status: CapabilityCheckStatus
    # Exception text for failures, skip reason for skips, empty on success.
    message: str = ""
    # Exception class name, for support diagnosis.
    error_type: str | None = None
    is_fallback: bool = False
    remediation: str | None = None
    docs_link: str | None = None
    duration_ms: int | None = None


class CredentialCapabilityReport(BaseModel):
    """The full outcome of one capability-check run for a credential."""

    credential_id: int
    source: DocumentSource
    # None means a config-less credential-time run.
    connector_id: int | None = None
    checked_at: datetime
    trigger: CapabilityCheckTrigger
    verdicts: dict[CredentialCapability, CapabilityVerdict]
    check_results: list[CapabilityCheckResult]


def compute_connector_config_hash(config: dict[str, Any] | None) -> str | None:
    """Returns the sha256 of the canonical config JSON a report ran with.

    This is the staleness signal, shared by every report writer so stored hashes
    stay comparable.
    """
    if config is None:
        return None
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def aggregate_capability_verdict(
    applicable: bool,
    results: Sequence[CapabilityCheckResult],
) -> CapabilityVerdict:
    """Rolls the per-check results of one capability up into a single verdict.

    Pure function, evaluated in strict precedence order. Required checks gate
    the verdict: a required FAILED is FAILED, and a required INDETERMINATE or
    SKIPPED leaves the capability's core unverified, so no pass-ish claim may be
    made. Non-required failures and indeterminates only downgrade to
    PASSED_WITH_WARNINGS (partial capability); non-required skips do not
    downgrade at all. An empty result list aggregates to SKIPPED: a capability
    is never PASSED on the basis of having checked nothing.
    """
    if not applicable:
        return CapabilityVerdict.NOT_APPLICABLE
    if any(
        result.status == CapabilityCheckStatus.FAILED and result.required
        for result in results
    ):
        return CapabilityVerdict.FAILED
    if any(
        result.status == CapabilityCheckStatus.INDETERMINATE and result.required
        for result in results
    ):
        return CapabilityVerdict.INDETERMINATE
    if any(
        result.status == CapabilityCheckStatus.SKIPPED and result.required
        for result in results
    ):
        return CapabilityVerdict.SKIPPED
    if any(
        result.status
        in (CapabilityCheckStatus.FAILED, CapabilityCheckStatus.INDETERMINATE)
        for result in results
    ):
        return CapabilityVerdict.PASSED_WITH_WARNINGS
    if all(result.status == CapabilityCheckStatus.SKIPPED for result in results):
        return CapabilityVerdict.SKIPPED
    return CapabilityVerdict.PASSED


def compute_capability_verdicts(
    applicable_capabilities: set[CredentialCapability],
    results: Sequence[CapabilityCheckResult],
) -> dict[CredentialCapability, CapabilityVerdict]:
    """Computes a verdict for every capability, applicable or not."""
    return {
        capability: aggregate_capability_verdict(
            capability in applicable_capabilities,
            [result for result in results if result.capability == capability],
        )
        for capability in CredentialCapability
    }
