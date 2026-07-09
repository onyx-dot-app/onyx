"""Pre-commit guard for recommended-models.json.

The auto-mode config resolver picks the newer of the GitHub-hosted config and
the bundled copy by `updated_at`, so an edit that forgets to bump the
timestamp would silently never win against the remote file. Fail the commit
when the file's content changes without a strictly newer `updated_at`.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from datetime import timezone

CONFIG_PATH = "backend/onyx/llm/well_known_providers/recommended-models.json"


def _parse_updated_at(raw_config: str) -> datetime:
    dt = datetime.fromisoformat(
        json.loads(raw_config)["updated_at"].replace("Z", "+00:00")
    )
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def main() -> int:
    # pre-commit sets PRE_COMMIT_FROM_REF for from-ref runs (e.g. CI over a
    # commit range); plain commits compare against HEAD.
    base_ref = os.environ.get("PRE_COMMIT_FROM_REF") or "HEAD"
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{CONFIG_PATH}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # File doesn't exist at the base ref (newly added) — nothing to check.
        return 0

    with open(CONFIG_PATH, "r") as f:
        new_raw = f.read()

    if json.loads(result.stdout) == json.loads(new_raw):
        return 0

    old_ts = _parse_updated_at(result.stdout)
    new_ts = _parse_updated_at(new_raw)
    if new_ts <= old_ts:
        print(
            f"{CONFIG_PATH} changed but updated_at was not bumped "
            f"(still {new_ts.isoformat()}, base has {old_ts.isoformat()}).\n"
            "Deployments resolve the newest config by updated_at, so this "
            "edit would never take effect. Bump updated_at (and version)."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
