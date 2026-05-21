"""Codified built-in skill definitions.

``BUILT_IN_SKILLS`` is the source of truth for which built-ins exist.
``db.skill.seed_built_in_skills`` mirrors one row per entry into each
tenant's ``skill`` table at boot, so the listing and fileset code can
treat built-ins and custom skills uniformly.

Built-in rows are not admin-mutable — see ``_ensure_custom`` in the
skill API. Visibility still goes through ``is_available(db)`` so a
built-in can hide itself when its runtime dependencies aren't met.
"""

import re
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.server.features.build.configs import SKILLS_TEMPLATE_PATH

_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


def _always_available(_: Session) -> bool:
    return True


class BuiltInSkillDefinition(BaseModel):
    """``built_in_skill_id`` is the stable identifier (also the seed
    slug and on-disk directory name). ``source_dir`` is an explicit
    field so tests can override it with a tmp_path."""

    model_config = ConfigDict(frozen=True)

    # Must match the slug grammar enforced for custom bundles (see
    # SLUG_REGEX in skills/bundle.py): doubles as the seeded ``slug`` and
    # the directory name under SKILLS_TEMPLATE_PATH, so an invalid value
    # would silently violate uploads and on-disk lookups.
    built_in_skill_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    has_template: bool
    source_dir: Path
    is_available: Callable[[Session], bool] = _always_available
    unavailable_reason: str | None = None

    def read_metadata(self) -> tuple[str, str]:
        """Return ``(name, description)`` from the SKILL.md frontmatter.
        Raises ``ValueError`` if missing or malformed — the seeder
        treats that as a hard failure."""
        filename = "SKILL.md.template" if self.has_template else "SKILL.md"
        path = self.source_dir / filename
        content = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(content)
        if match is None:
            raise ValueError(f"{path}: missing or malformed YAML frontmatter")

        parsed = yaml.safe_load(match.group("frontmatter")) or {}
        if not isinstance(parsed, dict):
            raise ValueError(f"{path}: frontmatter is not a mapping")

        name = parsed.get("name")
        description = parsed.get("description")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path}: frontmatter missing 'name'")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{path}: frontmatter missing 'description'")
        return name, description


def _def(built_in_skill_id: str, *, has_template: bool) -> BuiltInSkillDefinition:
    return BuiltInSkillDefinition(
        built_in_skill_id=built_in_skill_id,
        has_template=has_template,
        source_dir=Path(SKILLS_TEMPLATE_PATH) / built_in_skill_id,
    )


BUILT_IN_SKILLS: dict[str, BuiltInSkillDefinition] = {
    "pptx": _def("pptx", has_template=False),
    "image-generation": _def("image-generation", has_template=False),
    "company-search": _def("company-search", has_template=True),
}
