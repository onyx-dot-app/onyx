"""Git details of the running build, shown on the app's About page."""

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel


class BuildInfo(BaseModel):
    commit: str | None = None
    # ISO 8601 committer date.
    commit_date: str | None = None
    # The tag or branch the build came from.
    ref: str | None = None


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


def _load_build_info() -> BuildInfo:
    # Release images get these env vars at build time. A server run from a
    # checkout (local dev) reads the same details from git.
    commit = os.environ.get("ONYX_COMMIT_SHA") or None
    if commit:
        return BuildInfo(
            commit=commit,
            commit_date=os.environ.get("ONYX_COMMIT_DATE") or None,
            ref=os.environ.get("ONYX_GIT_REF") or None,
        )
    return BuildInfo(
        commit=_git("rev-parse", "HEAD"),
        commit_date=_git("log", "-1", "--format=%cI"),
        ref=_git("rev-parse", "--abbrev-ref", "HEAD"),
    )


BUILD_INFO = _load_build_info()
