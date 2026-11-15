"""Git details of the running build, shown on the app's About page."""

import os
import subprocess
from functools import cache
from pathlib import Path

from onyx.server.settings.models import BuildInfo

# Release images get these env vars at build time.
_ENV_COMMIT = os.environ.get("ONYX_COMMIT_SHA") or None
_ENV_BUILD_INFO = (
    BuildInfo(
        commit=_ENV_COMMIT,
        commit_date=os.environ.get("ONYX_COMMIT_DATE") or None,
        ref=os.environ.get("ONYX_GIT_REF") or None,
    )
    if _ENV_COMMIT
    else None
)


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _git_ref() -> str | None:
    tag = _git("describe", "--tags", "--exact-match")
    if tag:
        return tag
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    # A detached checkout reports "HEAD", which names no ref.
    return branch if branch != "HEAD" else None


@cache
def get_build_info() -> BuildInfo:
    """The env vars of a release image, or else the details of the checkout
    the server runs from (local dev). Git runs on the first call, not on
    import, and the result is kept."""
    if _ENV_BUILD_INFO:
        return _ENV_BUILD_INFO
    return BuildInfo(
        commit=_git("rev-parse", "HEAD"),
        commit_date=_git("log", "-1", "--format=%cI"),
        ref=_git_ref(),
    )
