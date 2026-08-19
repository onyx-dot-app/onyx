"""Doc-integrity check for the pptx built-in skill.

Every ``scripts/…`` path (``.py`` or ``.js``) referenced in the skill's
markdown must exist on disk, so docs and scripts can't silently drift apart."""

from __future__ import annotations

import re
from pathlib import Path

_PPTX_SKILL_DIR = Path(__file__).parents[4] / "onyx" / "skills" / "builtin" / "pptx"

_SCRIPT_REF_RE = re.compile(
    r"(?:\.opencode/skills/pptx/)?(scripts/[\w./-]+\.(?:py|js))"
)


def test_all_script_paths_referenced_in_docs_exist() -> None:
    md_files = sorted(_PPTX_SKILL_DIR.glob("*.md"))
    assert md_files, f"no markdown files found in {_PPTX_SKILL_DIR}"

    referenced: set[str] = set()
    for md_file in md_files:
        referenced.update(_SCRIPT_REF_RE.findall(md_file.read_text()))

    assert referenced, "expected at least one scripts/… reference in the docs"

    missing = sorted(ref for ref in referenced if not (_PPTX_SKILL_DIR / ref).is_file())
    assert not missing, f"docs reference nonexistent scripts: {missing}"
