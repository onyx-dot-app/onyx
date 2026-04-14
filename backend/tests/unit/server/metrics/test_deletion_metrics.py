"""Tests for deletion-specific Prometheus metrics."""

import pytest

from onyx.server.metrics.deletion_metrics import DELETION_BLOCKED
from onyx.server.metrics.deletion_metrics import DELETION_COMPLETED
from onyx.server.metrics.deletion_metrics import DELETION_FENCE_RESET
from onyx.server.metrics.deletion_metrics import DELETION_STARTED
from onyx.server.metrics.deletion_metrics import DELETION_TASKSET_DURATION
from onyx.server.metrics.deletion_metrics import inc_deletion_blocked
from onyx.server.metrics.deletion_metrics import inc_deletion_completed
from onyx.server.metrics.deletion_metrics import inc_deletion_fence_reset
from onyx.server.metrics.deletion_metrics import inc_deletion_started
from onyx.server.metrics.deletion_metrics import observe_deletion_taskset_duration


class TestIncDeletionStarted:
    def test_increments_counter(self) -> None:
        before = DELETION_STARTED.labels(tenant_id="t1")._value.get()

        inc_deletion_started("t1")

        after = DELETION_STARTED.labels(tenant_id="t1")._value.get()
        assert after == before + 1

    def test_labels_by_tenant(self) -> None:
        before_t1 = DELETION_STARTED.labels(tenant_id="t1")._value.get()
        before_t2 = DELETION_STARTED.labels(tenant_id="t2")._value.get()

        inc_deletion_started("t1")

        assert DELETION_STARTED.labels(tenant_id="t1")._value.get() == before_t1 + 1
        assert DELETION_STARTED.labels(tenant_id="t2")._value.get() == before_t2

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DELETION_STARTED,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_deletion_started("t1")


class TestIncDeletionCompleted:
    def test_increments_counter(self) -> None:
        before = DELETION_COMPLETED.labels(
            tenant_id="t1", outcome="success"
        )._value.get()

        inc_deletion_completed("t1", "success")

        after = DELETION_COMPLETED.labels(
            tenant_id="t1", outcome="success"
        )._value.get()
        assert after == before + 1

    def test_labels_by_outcome(self) -> None:
        before_success = DELETION_COMPLETED.labels(
            tenant_id="t1", outcome="success"
        )._value.get()
        before_failure = DELETION_COMPLETED.labels(
            tenant_id="t1", outcome="failure"
        )._value.get()

        inc_deletion_completed("t1", "success")

        assert (
            DELETION_COMPLETED.labels(tenant_id="t1", outcome="success")._value.get()
            == before_success + 1
        )
        assert (
            DELETION_COMPLETED.labels(tenant_id="t1", outcome="failure")._value.get()
            == before_failure
        )

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DELETION_COMPLETED,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_deletion_completed("t1", "success")


class TestObserveDeletionTasksetDuration:
    def test_observes_duration(self) -> None:
        before = DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="success"
        )._sum.get()

        observe_deletion_taskset_duration("t1", "success", 120.0)

        after = DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="success"
        )._sum.get()
        assert after == pytest.approx(before + 120.0)

    def test_labels_by_tenant(self) -> None:
        before_t1 = DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="success"
        )._sum.get()
        before_t2 = DELETION_TASKSET_DURATION.labels(
            tenant_id="t2", outcome="success"
        )._sum.get()

        observe_deletion_taskset_duration("t1", "success", 60.0)

        assert DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="success"
        )._sum.get() == pytest.approx(before_t1 + 60.0)
        assert DELETION_TASKSET_DURATION.labels(
            tenant_id="t2", outcome="success"
        )._sum.get() == pytest.approx(before_t2)

    def test_labels_by_outcome(self) -> None:
        before_success = DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="success"
        )._sum.get()
        before_failure = DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="failure"
        )._sum.get()

        observe_deletion_taskset_duration("t1", "failure", 45.0)

        assert DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="success"
        )._sum.get() == pytest.approx(before_success)
        assert DELETION_TASKSET_DURATION.labels(
            tenant_id="t1", outcome="failure"
        )._sum.get() == pytest.approx(before_failure + 45.0)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DELETION_TASKSET_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_deletion_taskset_duration("t1", "success", 10.0)


class TestIncDeletionBlocked:
    def test_increments_counter(self) -> None:
        before = DELETION_BLOCKED.labels(
            tenant_id="t1", blocker="indexing"
        )._value.get()

        inc_deletion_blocked("t1", "indexing")

        after = DELETION_BLOCKED.labels(tenant_id="t1", blocker="indexing")._value.get()
        assert after == before + 1

    def test_labels_by_blocker(self) -> None:
        before_idx = DELETION_BLOCKED.labels(
            tenant_id="t1", blocker="indexing"
        )._value.get()
        before_prune = DELETION_BLOCKED.labels(
            tenant_id="t1", blocker="pruning"
        )._value.get()

        inc_deletion_blocked("t1", "indexing")

        assert (
            DELETION_BLOCKED.labels(tenant_id="t1", blocker="indexing")._value.get()
            == before_idx + 1
        )
        assert (
            DELETION_BLOCKED.labels(tenant_id="t1", blocker="pruning")._value.get()
            == before_prune
        )

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DELETION_BLOCKED,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_deletion_blocked("t1", "indexing")


class TestIncDeletionFenceReset:
    def test_increments_counter(self) -> None:
        before = DELETION_FENCE_RESET.labels(tenant_id="t1")._value.get()

        inc_deletion_fence_reset("t1")

        after = DELETION_FENCE_RESET.labels(tenant_id="t1")._value.get()
        assert after == before + 1

    def test_labels_by_tenant(self) -> None:
        before_t1 = DELETION_FENCE_RESET.labels(tenant_id="t1")._value.get()
        before_t2 = DELETION_FENCE_RESET.labels(tenant_id="t2")._value.get()

        inc_deletion_fence_reset("t1")

        assert DELETION_FENCE_RESET.labels(tenant_id="t1")._value.get() == before_t1 + 1
        assert DELETION_FENCE_RESET.labels(tenant_id="t2")._value.get() == before_t2

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DELETION_FENCE_RESET,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_deletion_fence_reset("t1")
