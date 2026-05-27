"""Codified built-in skill definitions.

``_REGISTRY`` is the single source of truth: one provider per built-in skill,
one of two kinds —

- ``SeededBuiltInProvider``: a plain built-in skill whose ``skill`` rows are
  owned by Alembic migrations.
- ``ExternalAppBuiltInProvider``: a built-in skill backed by a connectable
  ``ExternalAppType``; rows are created on demand when an admin connects the app
  (``onyx.db.external_app.create_external_app``).

Both render through the identical disk-backed push path; the kind only governs
how the ``skill`` row comes to exist and whether an ``app_type`` connects to it.
Per-user availability of an external-app skill is gated on credentials by the
sandbox-injection query, not here.

Everything else is derived from the registry, which validates at import that no
two providers share a ``skill_id`` or an ``app_type``. Adding a built-in skill
or external app is a single ``_REGISTRY`` entry plus its on-disk
``skills/<skill_id>/`` directory.
"""

import re
from collections.abc import Callable
from collections.abc import Iterable
from pathlib import Path
from typing import Final
from typing import Literal

from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.server.features.build.configs import SKILLS_TEMPLATE_PATH

# Slug grammar shared with custom bundle slugs (bundle.py imports this).
SKILL_SLUG_PATTERN: Final[str] = r"^[a-z][a-z0-9-]{0,63}$"
SLUG_REGEX: Final[re.Pattern[str]] = re.compile(SKILL_SLUG_PATTERN)


def _always_available(_: Session) -> bool:
    return True


class BuiltInSkillDefinition(BaseModel):
    """Runtime behavior for one built-in skill (the resolved view a provider
    produces). ``built_in_skill_id`` is the stable identifier, seeded slug, and
    on-disk directory name under ``SKILLS_TEMPLATE_PATH`` — which fully
    determines ``source_dir`` and ``has_template``, so both are computed.

    ``extra="forbid"`` makes a stray ``source_dir=`` (e.g. an old test trying to
    inject one) fail loud rather than be silently dropped; redirect via
    ``SKILLS_TEMPLATE_PATH`` instead.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    built_in_skill_id: str = Field(pattern=SKILL_SLUG_PATTERN)
    is_available: Callable[[Session], bool] = _always_available
    unavailable_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_dir(self) -> Path:
        return Path(SKILLS_TEMPLATE_PATH) / self.built_in_skill_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_template(self) -> bool:
        # Disk-derived so it can't drift from the actual source layout.
        return (self.source_dir / "SKILL.md.template").exists()


class BuiltInProvider(BaseModel):
    """Base registry entry. ``skill_id`` doubles as the slug and on-disk dir
    name, validated here so a bad entry fails at import."""

    model_config = ConfigDict(frozen=True)

    kind: str
    skill_id: str = Field(pattern=SKILL_SLUG_PATTERN)
    is_available: Callable[[Session], bool] = _always_available
    unavailable_reason: str | None = None

    def to_definition(self) -> BuiltInSkillDefinition:
        # source_dir is derived by the definition from built_in_skill_id; the
        # declaration deliberately stays disk-layout-agnostic.
        return BuiltInSkillDefinition(
            built_in_skill_id=self.skill_id,
            is_available=self.is_available,
            unavailable_reason=self.unavailable_reason,
        )


class SeededBuiltInProvider(BuiltInProvider):
    """A plain built-in skill whose rows are seeded/managed by migrations."""

    kind: Literal["seeded"] = "seeded"


class ExternalAppBuiltInProvider(BuiltInProvider):
    """A built-in skill backed by a connectable external app."""

    kind: Literal["external_app"] = "external_app"
    app_type: ExternalAppType

    @model_validator(mode="after")
    def _reject_custom(self) -> "ExternalAppBuiltInProvider":
        # CUSTOM apps ship no bundled content — they stay bundle-backed rows.
        if self.app_type == ExternalAppType.CUSTOM:
            raise ValueError("CUSTOM apps have no bundled built-in skill content")
        return self


BuiltInProviderEntry = SeededBuiltInProvider | ExternalAppBuiltInProvider


class BuiltInSkillRegistry:
    """Owns the providers and the indices derived from them, failing at import
    if two providers collide on a ``skill_id`` or an ``app_type``.

    The derived maps are exposed as the same plain dicts the module re-exports:
    consumers bind ``BUILT_IN_SKILLS`` at import and tests inject temp built-ins
    via ``monkeypatch.setitem``, so the maps are intentionally mutable in place
    rather than read-only proxies.
    """

    def __init__(self, providers: Iterable[BuiltInProviderEntry]) -> None:
        provider_list = tuple(providers)
        definitions: dict[str, BuiltInSkillDefinition] = {}
        external_app_skill_ids: dict[ExternalAppType, str] = {}

        for provider in provider_list:
            if provider.skill_id in definitions:
                raise ValueError(f"Duplicate built-in skill_id: {provider.skill_id!r}")
            definitions[provider.skill_id] = provider.to_definition()

            if isinstance(provider, ExternalAppBuiltInProvider):
                existing = external_app_skill_ids.get(provider.app_type)
                if existing is not None:
                    raise ValueError(
                        f"Duplicate built-in external app for {provider.app_type}: "
                        f"{existing!r} and {provider.skill_id!r}"
                    )
                external_app_skill_ids[provider.app_type] = provider.skill_id

        self._definitions = definitions
        self._external_app_skill_ids = external_app_skill_ids

    @property
    def definitions_by_skill_id(self) -> dict[str, BuiltInSkillDefinition]:
        return self._definitions

    @property
    def external_app_skill_ids(self) -> dict[ExternalAppType, str]:
        return self._external_app_skill_ids


# Single source of truth.
_REGISTRY: Final = BuiltInSkillRegistry(
    providers=(
        SeededBuiltInProvider(skill_id="pptx"),
        SeededBuiltInProvider(skill_id="image-generation"),
        SeededBuiltInProvider(skill_id="company-search"),
        ExternalAppBuiltInProvider(skill_id="slack", app_type=ExternalAppType.SLACK),
        ExternalAppBuiltInProvider(skill_id="linear", app_type=ExternalAppType.LINEAR),
        ExternalAppBuiltInProvider(
            skill_id="google-calendar", app_type=ExternalAppType.GOOGLE_CALENDAR
        ),
    )
)

# Derived exports. ``Final`` pins the binding; the dicts stay mutable so tests
# can inject temp built-ins via ``monkeypatch.setitem``.
BUILT_IN_SKILLS: Final[dict[str, BuiltInSkillDefinition]] = (
    _REGISTRY.definitions_by_skill_id
)
EXTERNAL_APP_BUILT_IN_SKILL_IDS: Final[dict[ExternalAppType, str]] = (
    _REGISTRY.external_app_skill_ids
)

# Named handles so callers avoid bare slug literals.
COMPANY_SEARCH: Final[BuiltInSkillDefinition] = BUILT_IN_SKILLS["company-search"]
SLACK: Final[BuiltInSkillDefinition] = BUILT_IN_SKILLS["slack"]
