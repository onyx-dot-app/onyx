"""Filesystem anchors for tests that read files outside their own package."""

from __future__ import annotations

from pathlib import Path


def find_ancestor_containing(marker: str) -> Path:
    """Nearest ancestor directory of the tests tree containing ``marker``.

    Marker-based upward search instead of hardcoded ``parents[N]`` indices, so
    the resolved directory stays correct when test files move.
    """
    anchor = Path(__file__).resolve()
    for parent in anchor.parents:
        if (parent / marker).exists():
            return parent
    raise RuntimeError(f"no ancestor of {anchor} contains {marker!r}")
