"""Codified built-in skill definitions (runtime behavior only).

``BUILT_IN_SKILLS`` defines built-in behavior (``source_dir``,
``has_template``, ``is_available``). The ``skill`` table *rows* are owned
by Alembic migrations — adding/changing a built-in requires a migration.

Removing an entry leaves orphan rows: runtime skips them (with a warning),
but a retiring migration should delete them.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Final

from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.server.features.build.configs import SKILLS_TEMPLATE_PATH

# Slug grammar shared with custom bundle slugs (bundle.py imports this).
SKILL_SLUG_PATTERN: Final[str] = r"^[a-z][a-z0-9-]{0,63}$"
SLUG_REGEX: Final[re.Pattern[str]] = re.compile(SKILL_SLUG_PATTERN)


def _always_available(_: Session) -> bool:
    return True


class BuiltInSkillDefinition(BaseModel):
    """``built_in_skill_id`` is the stable identifier — also the seeded
    slug and on-disk directory name under SKILLS_TEMPLATE_PATH."""

    model_config = ConfigDict(frozen=True)

    built_in_skill_id: str = Field(pattern=SKILL_SLUG_PATTERN)
    source_dir: Path
    is_available: Callable[[Session], bool] = _always_available
    unavailable_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_template(self) -> bool:
        # Disk-derived so it can't drift from the actual source layout.
        return (self.source_dir / "SKILL.md.template").exists()


def _def(built_in_skill_id: str) -> BuiltInSkillDefinition:
    return BuiltInSkillDefinition(
        built_in_skill_id=built_in_skill_id,
        source_dir=Path(SKILLS_TEMPLATE_PATH) / built_in_skill_id,
    )


# Named handles so callers avoid bare slug literals (e.g. push.py dispatch).
PPTX = _def("pptx")
IMAGE_GENERATION = _def("image-generation")
COMPANY_SEARCH = _def("company-search")

BUILT_IN_SKILLS: dict[str, BuiltInSkillDefinition] = {
    d.built_in_skill_id: d for d in (PPTX, IMAGE_GENERATION, COMPANY_SEARCH)
}
