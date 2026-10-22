"""The runner starts every check whose dependencies have results, side by
side up to ``MAX_PARALLEL_CHECKS``: these tests pin the parallel start, the
cap, the stop after a rate limit, dependency stops, discovery last, tenant
context in check threads and the run-order report. Checks block on events and
barriers that only the expected schedule releases, so a wrong schedule fails
on a timeout instead of passing by chance."""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future, wait
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import runner
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckNotRunReason,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    RateLimitedValidationError,
)
from onyx.connectors.interfaces import BaseConnector
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Bounds every wait, so a wrong schedule fails instead of hanging.
_WAIT_SECONDS = 10


class _Check(CapabilityCheck):
    def __init__(
        self,
        check_id: str,
        body: Callable[[], object] = lambda: None,
        *,
        depends_on: tuple[str, ...] = (),
        discovery: bool = False,
        requires_connector_instance: bool = False,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=f"Run {check_id}",
            requires_connector_instance=requires_connector_instance,
            discovery=discovery,
            depends_on=depends_on,
        )
        self._body = body
        self.calls = 0

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:  # noqa: ARG002
        self.calls += 1
        self._body()
        return None


class _Recorded:
    """Sets one event per check_id when the runner records its result."""

    def __init__(self, check_ids: Sequence[str]) -> None:
        self.events: dict[str, threading.Event] = {
            check_id: threading.Event() for check_id in check_ids
        }
        self.order: list[str] = []

    def on_result(self, results: Sequence[CapabilityCheckResult]) -> None:
        newest = results[-1]
        self.order.append(newest.check_id)
        self.events[newest.check_id].set()

    def wait_for(self, check_id: str) -> Callable[[], None]:
        def wait() -> None:
            if not self.events[check_id].wait(_WAIT_SECONDS):
                raise RuntimeError(f"{check_id} was never recorded")

        return wait


def _run(
    checks: list[CapabilityCheck],
    on_result: Callable[[Sequence[CapabilityCheckResult]], None] | None = None,
    connector: BaseConnector | None = None,
) -> list[CapabilityCheckResult]:
    context = CapabilityCheckContext(
        source=DocumentSource.SLACK, credential_json={}, connector=connector
    )
    return run_capability_checks(checks, context, on_result=on_result)


def _by_id(results: list[CapabilityCheckResult]) -> dict[str, CapabilityCheckResult]:
    return {result.check_id: result for result in results}


def test_independent_checks_run_side_by_side_and_a_dependent_after() -> None:
    """Each of the three checks passes only if all three run at once."""
    barrier = threading.Barrier(3, timeout=_WAIT_SECONDS)
    recorded = _Recorded(["a", "b", "c", "after"])

    def after_all() -> None:
        if not all(recorded.events[i].is_set() for i in ("a", "b", "c")):
            raise RuntimeError("started before its dependencies had results")

    results = _by_id(
        _run(
            [
                _Check("a", barrier.wait),
                _Check("b", barrier.wait),
                _Check("c", barrier.wait),
                _Check("after", after_all, depends_on=("a", "b", "c")),
            ],
            recorded.on_result,
        )
    )

    assert {r.status for r in results.values()} == {CapabilityCheckStatus.PASSED}


def test_no_more_than_the_cap_run_at_once() -> None:
    """A barrier of the cap's size trips only with that many checks running;
    a counter shows no more ever run."""
    cap = runner.MAX_PARALLEL_CHECKS
    barrier = threading.Barrier(cap, timeout=_WAIT_SECONDS)
    lock = threading.Lock()
    active = 0
    most_active = 0

    def body() -> None:
        nonlocal active, most_active
        with lock:
            active += 1
            most_active = max(most_active, active)
        barrier.wait()
        with lock:
            active -= 1

    results = _run([_Check(f"check_{i}", body) for i in range(2 * cap)])

    assert {r.status for r in results} == {CapabilityCheckStatus.PASSED}
    assert most_active == cap


def test_a_rate_limit_stops_new_checks_and_running_checks_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "MAX_PARALLEL_CHECKS", 2)
    recorded = _Recorded(["limited", "running", "later"])
    started = threading.Event()

    def limited() -> None:
        if not started.wait(_WAIT_SECONDS):
            raise RuntimeError("running never started")
        raise RateLimitedValidationError("Slow down.")

    def running() -> None:
        started.set()
        # Holds its slot until the rate limit is recorded.
        recorded.wait_for("limited")()

    later = _Check("later")
    results = _by_id(
        _run(
            [_Check("limited", limited), _Check("running", running), later],
            recorded.on_result,
        )
    )

    assert results["limited"].status == CapabilityCheckStatus.INCOMPLETE
    assert results["running"].status == CapabilityCheckStatus.PASSED
    assert later.calls == 0
    assert results["later"].not_run_reason == CheckNotRunReason.RATE_LIMITED


def test_a_rate_limit_during_another_checks_callback_stops_new_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rate limit arrives while ``on_result`` records another check, so
    the runner has not read it when the freed slot could start a check."""
    monkeypatch.setattr(runner, "MAX_PARALLEL_CHECKS", 2)
    futures: dict[str, Future[Any]] = {}
    start_thread_future = runner.start_thread_future

    def capture(func: Callable[[], Any], name: str) -> Future[Any]:
        future = start_thread_future(func, name=name)
        futures[name] = future
        return future

    monkeypatch.setattr(runner, "start_thread_future", capture)
    release = threading.Event()

    def limited() -> None:
        if not release.wait(_WAIT_SECONDS):
            raise RuntimeError("never released")
        raise RateLimitedValidationError("Slow down.")

    def on_result(results: Sequence[CapabilityCheckResult]) -> None:
        if results[-1].check_id != "fast":
            return
        release.set()
        limited_future = futures["capability-check-limited"]
        done, _ = wait([limited_future], timeout=_WAIT_SECONDS)
        if limited_future not in done:
            raise RuntimeError("limited never finished")

    later = _Check("later")
    results = _by_id(
        _run([_Check("fast"), _Check("limited", limited), later], on_result)
    )

    assert results["limited"].status == CapabilityCheckStatus.INCOMPLETE
    assert later.calls == 0
    assert results["later"].not_run_reason == CheckNotRunReason.RATE_LIMITED


def test_the_report_keeps_run_order_while_progress_follows_completion() -> None:
    """c finishes first and a last; the report still reads a, b, c."""
    recorded = _Recorded(["a", "b", "c"])

    results = _run(
        [
            _Check("a", recorded.wait_for("b")),
            _Check("b", recorded.wait_for("c")),
            _Check("c"),
        ],
        recorded.on_result,
    )

    assert [result.check_id for result in results] == ["a", "b", "c"]
    assert recorded.order == ["c", "b", "a"]


def test_a_failed_check_stops_its_dependents_while_others_run() -> None:
    barrier = threading.Barrier(2, timeout=_WAIT_SECONDS)

    def fail() -> None:
        barrier.wait()
        raise CredentialExpiredError("Rejected.")

    dependent = _Check("dependent", depends_on=("sign_in",))
    results = _by_id(
        _run(
            [
                _Check("sign_in", fail),
                _Check("other", barrier.wait),
                dependent,
                _Check("after_other", depends_on=("other",)),
            ]
        )
    )

    assert results["sign_in"].status == CapabilityCheckStatus.FAILED
    assert dependent.calls == 0
    assert results["dependent"].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert results["dependent"].blocked_by == "sign_in"
    assert results["after_other"].status == CapabilityCheckStatus.PASSED


def test_discovery_checks_start_after_every_validation_check() -> None:
    recorded = _Recorded(["slow", "listing"])

    def after_validation() -> None:
        if not recorded.events["slow"].is_set():
            raise RuntimeError("discovery started before validation finished")

    results = _by_id(
        _run(
            [
                _Check("listing", after_validation, discovery=True),
                _Check("slow"),
            ],
            recorded.on_result,
        )
    )

    assert results["listing"].status == CapabilityCheckStatus.PASSED


def test_checks_run_with_the_callers_tenant() -> None:
    tenants: list[str | None] = []
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
    try:
        _run([_Check("a", lambda: tenants.append(CURRENT_TENANT_ID_CONTEXTVAR.get()))])
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert tenants == ["tenant_a"]


def test_checks_that_call_the_connector_run_one_at_a_time() -> None:
    """Connectors are not thread safe: two checks that need the connector
    instance never overlap, while a gateway check runs beside them."""
    lock = threading.Lock()
    in_connector = 0
    most_in_connector = 0
    gateway_ran_alongside = threading.Event()
    connector_started = threading.Event()

    def connector_body() -> None:
        nonlocal in_connector, most_in_connector
        with lock:
            in_connector += 1
            most_in_connector = max(most_in_connector, in_connector)
        connector_started.set()
        gateway_ran_alongside.wait(_WAIT_SECONDS)
        with lock:
            in_connector -= 1

    def gateway_body() -> None:
        if not connector_started.wait(_WAIT_SECONDS):
            raise RuntimeError("no connector check started")
        gateway_ran_alongside.set()

    results = _run(
        [
            _Check("settings", connector_body, requires_connector_instance=True),
            _Check("perm_sync", connector_body, requires_connector_instance=True),
            _Check("gateway", gateway_body),
        ],
        connector=MagicMock(spec=BaseConnector),
    )

    assert {r.status for r in results} == {CapabilityCheckStatus.PASSED}
    assert most_in_connector == 1
