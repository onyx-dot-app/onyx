from unittest.mock import patch

import pytest

from onyx.background.celery.tasks.docprocessing import tasks
from onyx.background.celery.tasks.docprocessing.tasks import (
    FULL_GC_INTERVAL_SECONDS,
    _collect_batch_garbage,
)

_FULL = ["unfreeze", "collect", "freeze"]


@pytest.fixture(autouse=True)
def _reset_last_full_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "_last_full_gc_at", None)


def _collect(now: float, calls: list[str]) -> None:
    with (
        patch.object(tasks.time, "monotonic", return_value=now),
        patch.object(
            tasks.gc, "unfreeze", side_effect=lambda: calls.append("unfreeze")
        ),
        patch.object(tasks.gc, "collect", side_effect=lambda: calls.append("collect")),
        patch.object(tasks.gc, "freeze", side_effect=lambda: calls.append("freeze")),
    ):
        _collect_batch_garbage()


def test_every_batch_collects_and_the_first_one_freezes() -> None:
    calls: list[str] = []
    _collect(100.0, calls)
    _collect(101.0, calls)

    assert calls == [*_FULL, "collect"]


def test_frozen_objects_are_collected_again_each_interval() -> None:
    calls: list[str] = []
    _collect(100.0, calls)
    _collect(100.0 + FULL_GC_INTERVAL_SECONDS / 2, calls)
    _collect(100.0 + FULL_GC_INTERVAL_SECONDS, calls)

    # Unfreeze comes first, or a cycle frozen with a batch is never collected.
    assert calls == [*_FULL, "collect", *_FULL]
