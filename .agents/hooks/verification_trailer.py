"""Check commit trailers and record unstamped commits."""

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

VALID_STAMP = re.compile(r"(?:e2e|integration|unit|none \([^()\n]*[^()\s][^()\n]*\))")


def git(*args: str, message: str | None = None) -> str:
    return subprocess.check_output(["git", *args], input=message, text=True).strip()


def has_stamp(message: str) -> bool:
    trailers = git("interpret-trailers", "--parse", message=message)
    values = [
        value.strip()
        for line in trailers.splitlines()
        for key, _, value in [line.partition(":")]
        if key.lower() == "verified-by"
    ]
    return len(values) == 1 and VALID_STAMP.fullmatch(values[0]) is not None


def export_claude_session() -> int:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    session = json.load(sys.stdin).get("session_id")
    if env_file and isinstance(session, str) and session:
        with Path(env_file).open("a", encoding="utf-8") as output:
            output.write(f"export ONYX_VERIFICATION_SESSION={shlex.quote(session)}\n")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--claude-session"]:
        return export_claude_session()

    mode = subprocess.run(
        ["git", "config", "--get", "onyx.verificationMode"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if mode == "off":
        return 0

    session = os.environ.get("ONYX_VERIFICATION_SESSION") or os.environ.get(
        "CODEX_SESSION_ID"
    )
    counter_name = "onyx-verification-blocks"
    if session:
        counter_name += f"-{sha256(session.encode()).hexdigest()}"
    counter = Path(git("rev-parse", "--git-path", counter_name))
    if len(sys.argv) == 1:
        counter.unlink(missing_ok=True)
        if not has_stamp(git("log", "-1", "--format=%B")):
            log = Path(git("rev-parse", "--git-path", "onyx-verification.log"))
            with log.open("a", encoding="utf-8") as output:
                output.write(
                    f"{datetime.now(UTC).isoformat()} {git('rev-parse', 'HEAD')} missing or invalid Verified-by\n"
                )
        return 0

    if mode != "enforce" or has_stamp(Path(sys.argv[1]).read_text(encoding="utf-8")):
        return 0

    blocks = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    if blocks >= 2:
        print("Allowing commit after two verification trailer blocks.", file=sys.stderr)
        return 0

    counter.write_text(str(blocks + 1), encoding="utf-8")
    print(
        "Add Verified-by: e2e, integration, unit, or none (short reason).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Verification trailer check could not run: {error}", file=sys.stderr)
