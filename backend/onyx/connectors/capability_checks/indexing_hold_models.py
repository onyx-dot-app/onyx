"""API shape of the hold on a pair's first index attempt. Import-light, so the
server models can carry it."""

from enum import Enum

from pydantic import BaseModel

from onyx.connectors.capabilities import CredentialCapability


class IndexingHoldReason(str, Enum):
    # A capability run for the pair is in flight.
    CHECKS_RUNNING = "checks_running"
    # The last run died before it stored a report, or the stored report cannot
    # be read; re-run the checks.
    CHECKS_FAILED_TO_RUN = "checks_failed_to_run"
    # A required check failed in the last completed run.
    REQUIRED_CHECKS_FAILED = "required_checks_failed"


class HeldCheck(BaseModel):
    """A required check that failed, as the connector page shows it."""

    check_id: str
    capability: CredentialCapability
    display_name: str
    message: str
    remediation: str | None = None
    docs_link: str | None = None


class IndexingHold(BaseModel):
    """Why the pair's first index attempt does not start yet."""

    reason: IndexingHoldReason
    # Set for REQUIRED_CHECKS_FAILED.
    failed_checks: list[HeldCheck] = []
    # The scheduled attempt that waits, when it is created.
    index_attempt_id: int | None = None
