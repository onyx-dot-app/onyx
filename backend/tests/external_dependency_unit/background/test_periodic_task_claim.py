"""External dependency unit tests for periodic task claiming.

Tests ``_try_claim_task`` and ``_try_run_periodic_task`` against real
PostgreSQL, verifying happy-path behavior and concurrent-access safety.

The claim mechanism uses a transaction-scoped advisory lock + a KVStore
timestamp for cross-instance dedup.  The DB session is released before
the task runs, so long-running tasks don't hold connections.
"""

import time
from collections.abc import Generator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.background.periodic_poller import _PeriodicTaskDef
from onyx.background.periodic_poller import _try_claim_task
from onyx.background.periodic_poller import _try_run_periodic_task
from onyx.background.periodic_poller import PERIODIC_TASK_KV_PREFIX
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import KVStore
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID

_TEST_LOCK_BASE = 90_000


@pytest.fixture(scope="module", autouse=True)
def _init_engine() -> None:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)


def _make_task(
    *,
    name: str | None = None,
    interval: float = 3600,
    lock_id: int | None = None,
    run_fn: MagicMock | None = None,
) -> _PeriodicTaskDef:
    return _PeriodicTaskDef(
        name=name if name is not None else f"test-{uuid4().hex[:8]}",
        interval_seconds=interval,
        lock_id=lock_id if lock_id is not None else _TEST_LOCK_BASE,
        run_fn=run_fn if run_fn is not None else MagicMock(),
    )


@pytest.fixture(autouse=True)
def _cleanup_kv(
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    yield
    with get_session_with_current_tenant() as db_session:
        db_session.query(KVStore).filter(
            KVStore.key.like(f"{PERIODIC_TASK_KV_PREFIX}test-%")
        ).delete(synchronize_session=False)
        db_session.commit()


# ------------------------------------------------------------------
# Happy-path: _try_claim_task
# ------------------------------------------------------------------


class TestClaimHappyPath:
    def test_first_claim_succeeds(self) -> None:
        assert _try_claim_task(_make_task()) is True

    def test_first_claim_creates_kv_row(self) -> None:
        task = _make_task()
        _try_claim_task(task)

        with get_session_with_current_tenant() as db_session:
            row = (
                db_session.query(KVStore)
                .filter_by(key=PERIODIC_TASK_KV_PREFIX + task.name)
                .first()
            )
        assert row is not None
        assert row.value is not None

    def test_second_claim_within_interval_fails(self) -> None:
        task = _make_task(interval=3600)
        assert _try_claim_task(task) is True
        assert _try_claim_task(task) is False

    def test_claim_after_interval_succeeds(self) -> None:
        task = _make_task(interval=1)
        assert _try_claim_task(task) is True

        kv_key = PERIODIC_TASK_KV_PREFIX + task.name
        with get_session_with_current_tenant() as db_session:
            row = db_session.query(KVStore).filter_by(key=kv_key).first()
            assert row is not None
            row.value = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            db_session.commit()

        assert _try_claim_task(task) is True


# ------------------------------------------------------------------
# Happy-path: _try_run_periodic_task
# ------------------------------------------------------------------


class TestRunHappyPath:
    def test_runs_task_and_updates_last_run_at(self) -> None:
        mock_fn = MagicMock()
        task = _make_task(run_fn=mock_fn)

        _try_run_periodic_task(task)

        mock_fn.assert_called_once()
        assert task.last_run_at > 0

    def test_skips_when_in_memory_interval_not_elapsed(self) -> None:
        mock_fn = MagicMock()
        task = _make_task(run_fn=mock_fn, interval=3600)
        task.last_run_at = time.monotonic()

        _try_run_periodic_task(task)

        mock_fn.assert_not_called()

    def test_skips_when_db_claim_blocked(self) -> None:
        name = f"test-{uuid4().hex[:8]}"
        lock_id = _TEST_LOCK_BASE + 10

        _try_claim_task(_make_task(name=name, lock_id=lock_id, interval=3600))

        mock_fn = MagicMock()
        task = _make_task(name=name, lock_id=lock_id, interval=3600, run_fn=mock_fn)
        _try_run_periodic_task(task)

        mock_fn.assert_not_called()

    def test_task_exception_does_not_propagate(self) -> None:
        task = _make_task(run_fn=MagicMock(side_effect=RuntimeError("boom")))
        _try_run_periodic_task(task)

    def test_claim_committed_before_task_runs(self) -> None:
        """The KV claim must be visible in the DB when run_fn executes."""
        task_name = f"test-order-{uuid4().hex[:8]}"
        kv_key = PERIODIC_TASK_KV_PREFIX + task_name
        claim_visible: list[bool] = []

        def check_claim() -> None:
            with get_session_with_current_tenant() as db_session:
                row = db_session.query(KVStore).filter_by(key=kv_key).first()
                claim_visible.append(row is not None and row.value is not None)

        task = _PeriodicTaskDef(
            name=task_name,
            interval_seconds=3600,
            lock_id=_TEST_LOCK_BASE + 11,
            run_fn=check_claim,
        )

        _try_run_periodic_task(task)

        assert claim_visible == [True]


# ------------------------------------------------------------------
# Concurrency: only one claimer should win
# ------------------------------------------------------------------


class TestClaimConcurrency:
    def test_concurrent_claims_single_winner(self) -> None:
        """Many threads claim the same task — exactly one should succeed."""
        num_threads = 20
        task_name = f"test-race-{uuid4().hex[:8]}"
        lock_id = _TEST_LOCK_BASE + 20

        def claim() -> bool:
            CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
            return _try_claim_task(
                _PeriodicTaskDef(
                    name=task_name,
                    interval_seconds=3600,
                    lock_id=lock_id,
                    run_fn=lambda: None,
                )
            )

        results: list[bool] = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(claim) for _ in range(num_threads)]
            for future in as_completed(futures):
                results.append(future.result())

        winners = sum(1 for r in results if r)
        assert winners == 1, f"Expected 1 winner, got {winners}"

    def test_concurrent_run_single_execution(self) -> None:
        """Many threads run the same task — run_fn fires exactly once."""
        num_threads = 20
        task_name = f"test-run-race-{uuid4().hex[:8]}"
        lock_id = _TEST_LOCK_BASE + 21
        counter = MagicMock()

        def run() -> None:
            CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
            _try_run_periodic_task(
                _PeriodicTaskDef(
                    name=task_name,
                    interval_seconds=3600,
                    lock_id=lock_id,
                    run_fn=counter,
                )
            )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(run) for _ in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        assert (
            counter.call_count == 1
        ), f"Expected run_fn called once, got {counter.call_count}"

    def test_no_errors_under_contention(self) -> None:
        """All threads complete without exceptions under high contention."""
        num_threads = 30
        task_name = f"test-err-{uuid4().hex[:8]}"
        lock_id = _TEST_LOCK_BASE + 22
        errors: list[Exception] = []

        def claim() -> bool:
            CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
            return _try_claim_task(
                _PeriodicTaskDef(
                    name=task_name,
                    interval_seconds=3600,
                    lock_id=lock_id,
                    run_fn=lambda: None,
                )
            )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(claim) for _ in range(num_threads)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append(e)

        assert errors == [], f"Got {len(errors)} errors: {errors}"
