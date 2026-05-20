"""File ops security boundary tests (pure-logic half).

Tests pin the contract for `_sanitize_path` and `_is_path_allowed` on
`LocalSandboxManager`. Both helpers are pure functions of their arguments
(they don't read instance state), so we bypass the singleton's heavy
`_initialize` by constructing via `object.__new__`.
"""

from __future__ import annotations

from pathlib import Path

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


def test_sanitize_path_strips_dotdot() -> None:
    """``_sanitize_path`` silently strips ``..`` components rather than raising."""
    manager = _bare_manager()
    result = manager._sanitize_path("../foo")
    assert result == "foo"


def test_sanitize_path_strips_leading_slash() -> None:
    """``_sanitize_path`` strips the leading ``/`` and returns the relative path."""
    manager = _bare_manager()
    result = manager._sanitize_path("/foo")
    assert result == "foo"


def test_sanitize_path_passes_null_byte_through() -> None:
    """``_sanitize_path`` does not strip or reject NUL bytes.

    The null-byte guard lives in the per-endpoint validation layer
    (e.g. ``delete_file``'s regex), not in ``_sanitize_path`` itself.
    """
    manager = _bare_manager()
    result = manager._sanitize_path("foo\x00bar")
    assert result == "foo\x00bar"


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
