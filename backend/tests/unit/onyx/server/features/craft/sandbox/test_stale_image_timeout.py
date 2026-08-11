"""Which clock the idle sweep reaps a sandbox on.

A sandbox provisioned on a sandbox image whose sources have since changed is
reclaimed sooner — sleeping is what moves it onto the current image, because
the user's next request provisions a fresh pod. The comparison is between
image content identities, not tags or releases: a deploy that re-tagged an
unchanged image reclaims nothing.

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
RUNNING_IMAGE = "ctx-aaaaaaaaaaaaaaaaaaaa"
OLD_IMAGE = "ctx-bbbbbbbbbbbbbbbbbbbb"
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
    image_identity: str | None = RUNNING_IMAGE,
) -> tuple[int | None, MagicMock]:
    manager = MagicMock()
    manager.provisioned_image_identity.return_value = provisioned
    timeout = sandbox_lifecycle.reap_timeout_seconds(
        manager, _sandbox(seconds_quiet), NOW, image_identity
    )
    return timeout, manager


def test_a_sandbox_on_a_superseded_image_is_reaped_on_the_short_clock() -> None:
    timeout, _ = _timeout(provisioned=OLD_IMAGE, seconds_quiet=600)

    assert timeout == SHORT


def test_a_sandbox_on_the_running_image_is_not_reaped_yet() -> None:
    """A deploy that re-tagged an unchanged image lands here: the release
    moved, the identity did not, and nothing is recycled."""
    timeout, _ = _timeout(provisioned=RUNNING_IMAGE, seconds_quiet=600)

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
    timeout, manager = _timeout(provisioned=OLD_IMAGE, seconds_quiet=seconds_quiet)

    assert timeout == expected, why
    manager.provisioned_image_identity.assert_not_called()


def test_no_computable_identity_means_no_read_and_no_early_reap() -> None:
    """An identity we cannot compute turns the comparison off."""
    timeout, manager = _timeout(
        provisioned=OLD_IMAGE, seconds_quiet=600, image_identity=None
    )

    assert timeout is IN_USE
    manager.provisioned_image_identity.assert_not_called()


def test_an_unlabelled_sandbox_keeps_the_normal_clock() -> None:
    """Provisioned before this shipped: unknown, never behind."""
    timeout, _ = _timeout(provisioned=None, seconds_quiet=600)

    assert timeout is IN_USE


def test_a_backend_that_raises_does_not_reap_early() -> None:
    """Fail closed: it stays in use and gets the normal clock later."""
    manager = MagicMock()
    manager.provisioned_image_identity.side_effect = RuntimeError("api is unwell")

    timeout = sandbox_lifecycle.reap_timeout_seconds(
        manager, _sandbox(600), NOW, RUNNING_IMAGE
    )

    assert timeout is IN_USE
