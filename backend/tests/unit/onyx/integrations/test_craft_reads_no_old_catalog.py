"""Craft finds its integrations through plugins. This test fails when code
reads ``mcp_server.available_in_craft`` or the old task allow-list again."""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4]
SCANNED = [BACKEND / "onyx", BACKEND / "ee"]
# A read of the column; an assignment (a write for rollback) is allowed.
AVAILABLE_IN_CRAFT_READ = re.compile(r"\.available_in_craft\b(?!\s*=[^=])")
OLD_TASK_TABLES = re.compile(
    r"\b(ScheduledTaskEnabledApp|ScheduledTaskActionPolicy|get_craft_enabled_mcp_servers)\b"
)
# The column definition names the field; it is not a read.
ALLOWED_FILES = {
    BACKEND / "onyx" / "db" / "models.py",
}


def _hits(pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for root in SCANNED:
        for path in sorted(root.rglob("*.py")):
            if path in ALLOWED_FILES:
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if pattern.search(line) and "request.available_in_craft" not in line:
                    hits.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    return hits


def test_no_code_reads_available_in_craft() -> None:
    assert _hits(AVAILABLE_IN_CRAFT_READ) == []


def test_no_code_reads_the_old_task_allow_list() -> None:
    assert _hits(OLD_TASK_TABLES) == []
