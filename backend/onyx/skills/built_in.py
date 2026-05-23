"""Codified built-in skill definitions (runtime behavior only).

``BUILT_IN_SKILLS`` defines built-in behavior (``source_dir``,
``has_template``, ``is_available``) for every built-in, regardless of how its
``skill`` table *row* comes to exist:

- **Seeded built-ins** (``pptx``, ``image-generation``, ``company-search``):
  their rows are owned by Alembic migrations — adding/changing one requires a
  migration. Removing an entry leaves orphan rows: runtime skips them (with a
  warning), but a retiring migration should delete them.

- **External-app built-ins** (``slack``, ``google-calendar``, ``linear``):
  *not* seeded. A row is created on demand when an admin connects the app
  (``onyx.db.external_app.create_external_app``), with ``built_in_skill_id``
  set so it renders through the exact same disk-backed path as a seeded
  built-in. ``EXTERNAL_APP_BUILT_IN_SKILL_IDS`` maps each provider's
  ``ExternalAppType`` to its built-in id (also the slug + on-disk dir). Per-user
  availability is gated on credentials by the sandbox-injection query, not here.
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

from onyx.db.enums import ExternalAppType
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

# External-app providers that ship built-in skill content. Rows are created on
# demand by ``create_external_app`` (never seeded), so these definitions exist
# purely so the push path can render their on-disk content like any built-in.
GOOGLE_CALENDAR = _def("google-calendar")
SLACK = _def("slack")
LINEAR = _def("linear")

BUILT_IN_SKILLS: dict[str, BuiltInSkillDefinition] = {
    d.built_in_skill_id: d
    for d in (
        PPTX,
        IMAGE_GENERATION,
        COMPANY_SEARCH,
        GOOGLE_CALENDAR,
        SLACK,
        LINEAR,
    )
}

# Maps an external-app provider's ``ExternalAppType`` to its built-in skill id
# (== slug == on-disk dir). Only providers that ship bundled skill content
# appear here; ``CUSTOM`` apps have none and stay custom (bundle-backed) rows.
EXTERNAL_APP_BUILT_IN_SKILL_IDS: dict[ExternalAppType, str] = {
    ExternalAppType.GOOGLE_CALENDAR: GOOGLE_CALENDAR.built_in_skill_id,
    ExternalAppType.SLACK: SLACK.built_in_skill_id,
    ExternalAppType.LINEAR: LINEAR.built_in_skill_id,
}
