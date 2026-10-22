"""A stored draft run and its latest-run marker outlive the run's lease."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import draft_runs
from onyx.connectors.capability_checks.draft_runs import (
    DRAFT_RUN_TTL_SECONDS,
    DraftCheckRunSnapshot,
    DraftRunStatus,
    StoredDraftRun,
)


def _run() -> StoredDraftRun:
    return StoredDraftRun(
        user_id=uuid4(),
        snapshot=DraftCheckRunSnapshot(
            run_id=uuid4(),
            draft_key="draft",
            source=DocumentSource.SLACK,
            credential_id=1,
            access_type=None,
            status=DraftRunStatus.RUNNING,
            form_errors={},
            unknown_fields=[],
            checks=[],
        ),
        result_cache_keys={},
    )


@pytest.mark.parametrize("lease_seconds", [None, 60, 4 * DRAFT_RUN_TTL_SECONDS])
def test_run_and_marker_ttls_cover_the_lease(
    monkeypatch: pytest.MonkeyPatch, lease_seconds: int | None
) -> None:
    cache = MagicMock()
    monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: cache)
    run = _run()
    if lease_seconds is not None:
        run.renew_lease(lease_seconds)

    draft_runs.save_draft_run(run)
    draft_runs.set_latest_draft_run(run)

    run_set, marker_set = cache.set.call_args_list
    ttls = [
        run_set.kwargs["ex"],
        marker_set.kwargs["ex"],
        cache.renew_if_value.call_args.args[2],
    ]
    for ttl in ttls:
        assert ttl >= DRAFT_RUN_TTL_SECONDS
        assert ttl > (lease_seconds or 0)
