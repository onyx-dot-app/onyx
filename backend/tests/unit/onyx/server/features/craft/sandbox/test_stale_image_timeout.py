"""Which clock the idle sweep reaps a sandbox on.

A sandbox provisioned by an earlier release is on the sandbox image that
shipped with it, so it is reclaimed sooner — sleeping is what
moves it onto the current image, because the user's next request provisions a
fresh pod.

The sandbox is only inspected inside the window where that answer changes something,
which is what keeps this from growing with the fleet or the tenant count.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.server.features.build.session import sandbox_lifecycle

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
RUNNING_RELEASE = "2.0.0"
OLD_RELEASE = "1.0.0"
NORMAL = 3600
SHORT = 300
# Not reapable on either clock.
IN_USE = None


def _sandbox(seconds_quiet: int) -> Any:
    return SimpleNamespace(
        id=MagicMock(),
        last_heartbeat=NOW - timedelta(seconds=seconds_quiet),
        created_at=NOW,
    )


def _timeout(
    provisioned: str | None,
    seconds_quiet: int,
    release: str | None = RUNNING_RELEASE,
) -> tuple[int | None, MagicMock]:
    manager = MagicMock()
    manager.provisioned_release.return_value = provisioned
    timeout = sandbox_lifecycle.reap_timeout_seconds(
        manager, _sandbox(seconds_quiet), NOW, release
    )
    return timeout, manager


def test_a_sandbox_from_an_earlier_release_is_reaped_on_the_short_clock() -> None:
    timeout, _ = _timeout(provisioned=OLD_RELEASE, seconds_quiet=600)

    assert timeout == SHORT


def test_a_sandbox_from_the_running_release_is_not_reaped_yet() -> None:
    timeout, _ = _timeout(provisioned=RUNNING_RELEASE, seconds_quiet=600)

    assert timeout is IN_USE


@pytest.mark.parametrize(
    "seconds_quiet,expected,why",
    [
        (60, IN_USE, "below the short timeout, so the answer cannot change anything"),
        (7200, NORMAL, "past the normal timeout, so it is reaped either way"),
    ],
)
def test_the_sandbox_is_not_inspected_outside_the_window(
    seconds_quiet: int, expected: int | None, why: str
) -> None:
    """An ordinary sweep touches no pods at all."""
    timeout, manager = _timeout(provisioned=OLD_RELEASE, seconds_quiet=seconds_quiet)

    assert timeout == expected, why
    manager.provisioned_release.assert_not_called()


def test_an_unusable_release_means_no_read_and_no_early_reap() -> None:
    """A version that cannot be a label value turns the comparison off."""
    timeout, manager = _timeout(
        provisioned=OLD_RELEASE, seconds_quiet=600, release=None
    )

    assert timeout is IN_USE
    manager.provisioned_release.assert_not_called()


def test_an_unlabelled_sandbox_keeps_the_normal_clock() -> None:
    """Provisioned before this shipped: unknown, never behind."""
    timeout, _ = _timeout(provisioned=None, seconds_quiet=600)

    assert timeout is IN_USE


def test_a_backend_that_raises_does_not_reap_early() -> None:
    """Fail closed: it stays in use and gets the normal clock later."""
    manager = MagicMock()
    manager.provisioned_release.side_effect = RuntimeError("api is unwell")

    timeout = sandbox_lifecycle.reap_timeout_seconds(
        manager, _sandbox(600), NOW, RUNNING_RELEASE
    )

    assert timeout is IN_USE
