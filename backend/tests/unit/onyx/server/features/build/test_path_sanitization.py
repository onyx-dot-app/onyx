"""Cluster P - File ops security boundary (pure-logic half).

Tests pin the contract for `_sanitize_path` and `_is_path_allowed` on
`LocalSandboxManager`. Both helpers are pure functions of their arguments
(they don't read instance state), so we bypass the singleton's heavy
`_initialize` by constructing via `object.__new__`.

See `docs/craft/test-master-plan.md` Cluster P.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from onyx.server.features.build.sandbox.local.local_sandbox_manager import (
    LocalSandboxManager,
)


def _bare_manager() -> LocalSandboxManager:
    """Build a LocalSandboxManager without running `_initialize`.

    `_sanitize_path` and `_is_path_allowed` don't touch instance state, so
    skipping `_initialize` (which validates templates on disk) lets us keep
    these tests in the pure-unit layer with no external dependencies.
    """
    return object.__new__(LocalSandboxManager)


@pytest.mark.xfail(
    strict=True,
    reason=("sanitize_path strips '..' instead of raising; plan calls for ValueError."),
)
def test_sanitize_path_rejects_dotdot() -> None:
    """A path containing a '..' component must be rejected outright."""
    manager = _bare_manager()
    with pytest.raises(ValueError):
        manager._sanitize_path("../foo")


@pytest.mark.xfail(
    strict=True,
    reason=("sanitize_path strips '..' instead of raising; plan calls for ValueError."),
)
def test_sanitize_path_rejects_absolute() -> None:
    """An absolute path like '/foo' must be rejected."""
    manager = _bare_manager()
    with pytest.raises(ValueError):
        manager._sanitize_path("/foo")


@pytest.mark.xfail(
    strict=True,
    reason=("sanitize_path strips '..' instead of raising; plan calls for ValueError."),
)
def test_sanitize_path_rejects_null_byte() -> None:
    """A path containing a NUL byte must be rejected."""
    manager = _bare_manager()
    with pytest.raises(ValueError):
        manager._sanitize_path("foo\x00bar")


def test_is_path_allowed_blocks_outside_base(tmp_path: Path) -> None:
    """A symlink whose target resolves outside the session base returns False."""
    manager = _bare_manager()

    session_base = tmp_path / "session"
    session_base.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")

    escape_link = session_base / "escape"
    escape_link.symlink_to(outside)

    # Resolving via the symlink lands outside the session base.
    target_via_symlink = escape_link / "secret.txt"
    assert manager._is_path_allowed(session_base, target_via_symlink) is False

    # Sanity: a path inside the session base is allowed.
    inside = session_base / "ok.txt"
    inside.write_text("fine")
    assert manager._is_path_allowed(session_base, inside) is True
