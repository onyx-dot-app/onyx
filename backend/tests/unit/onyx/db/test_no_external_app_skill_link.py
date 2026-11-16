"""No code reads or writes the old app-to-skill link (``external_app__skill``).

The model stays in ``onyx/db/models.py`` for a rollback until the table goes;
the migrations keep their history."""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SEARCHED = ("backend/onyx", "backend/ee", "web/src")
_ALLOWED = {Path("backend/onyx/db/models.py")}
_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}
_PATTERN = re.compile(r"external_app__skill|ExternalApp__Skill|associated_skills")


def test_no_code_uses_the_app_skill_link() -> None:
    offenders: list[str] = []
    for root in _SEARCHED:
        directory = _REPO_ROOT / root
        assert directory.is_dir(), directory
        for path in directory.rglob("*"):
            if (
                path.suffix not in _SUFFIXES
                or "node_modules" in path.parts
                or not path.is_file()
            ):
                continue
            relative = path.relative_to(_REPO_ROOT)
            if relative in _ALLOWED:
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if _PATTERN.search(line):
                    offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
