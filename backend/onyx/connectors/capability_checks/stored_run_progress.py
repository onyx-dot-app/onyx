"""Per-check progress of a stored capability run while it is RUNNING.

A stored run writes its report only when it completes. Until then, the
pair's checks card reads this cache entry, keyed by the run's ``run_id``,
to show the finished, running and queued checks.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from onyx.cache.factory import get_cache_backend
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckState,
    DraftCheckStateKind,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckResult,
)

_KEY_PREFIX = "capability_check_stored_run_progress"


class StoredRunProgress(BaseModel):
    """The run's finished checks, and the checks still to finish in run
    order: the first RUNNING, the rest PENDING."""

    check_results: list[CapabilityCheckResult]
    open_checks: list[DraftCheckState]


def _key(run_id: UUID) -> str:
    return f"{_KEY_PREFIX}:{run_id}"


def _open_state(check: CapabilityCheck[Any]) -> DraftCheckState:
    return DraftCheckState(
        check_id=check.check_id,
        display_name=check.display_name,
        capability=check.capability,
        required=check.required,
        state=DraftCheckStateKind.PENDING,
        remediation=check.remediation,
        docs_link=check.docs_link,
        is_fallback=check.is_fallback,
        validates_binding=check.validates_binding,
        discovery=check.discovery,
    )


class StoredRunProgressRecorder:
    """Saves the progress of one stored run as its checks finish."""

    def __init__(
        self,
        run_id: UUID,
        checks: Sequence[CapabilityCheck[Any]],
        prior_results: Sequence[CapabilityCheckResult],
        ttl: timedelta,
    ) -> None:
        self._run_id = run_id
        self._ttl_seconds = max(1, int(ttl.total_seconds()))
        self._prior = list(prior_results)
        # The runner executes discovery checks last.
        ordered = [check for check in checks if not check.discovery] + [
            check for check in checks if check.discovery
        ]
        self._open = [_open_state(check) for check in ordered]
        self._results: list[CapabilityCheckResult] = []

    def start(self) -> None:
        self._save()

    def on_result(self, results: Sequence[CapabilityCheckResult]) -> None:
        self._results = list(results)
        self._open = [
            check
            for check in self._open
            if not any(
                result.check_id == check.check_id
                and result.capability == check.capability
                for result in results
            )
        ]
        self._save()

    def _save(self) -> None:
        open_checks = [
            check.model_copy(
                update={
                    "state": (
                        DraftCheckStateKind.RUNNING
                        if index == 0
                        else DraftCheckStateKind.PENDING
                    )
                }
            )
            for index, check in enumerate(self._open)
        ]
        progress = StoredRunProgress(
            check_results=[*self._prior, *self._results],
            open_checks=open_checks,
        )
        get_cache_backend().set(
            _key(self._run_id), progress.model_dump_json(), ex=self._ttl_seconds
        )


def load_stored_run_progress(run_id: UUID) -> StoredRunProgress | None:
    raw = get_cache_backend().get(_key(run_id))
    return StoredRunProgress.model_validate_json(raw) if raw is not None else None
