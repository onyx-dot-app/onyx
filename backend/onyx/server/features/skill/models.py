"""Pydantic request and response models for the skills API."""

import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.skill import SkillPatch
from onyx.skills.built_in import BuiltInSkillDefinition


class BuiltinSkillResponse(BaseModel):
    """A built-in skill — backed by a ``skill`` row whose
    ``built_in_skill_id`` references a definition in
    ``onyx.skills.built_in.BUILT_IN_SKILLS``. Display fields come from
    the row; ``is_available`` / ``unavailable_reason`` come from the
    codified definition. Built-ins are not admin-mutable, so lifecycle
    fields (``enabled``, ``is_public``, group grants) are not part of
    this response — they're row-level implementation detail."""

    source: Literal["builtin"] = "builtin"
    slug: str
    name: str
    description: str
    is_available: bool
    unavailable_reason: str | None = None

    @classmethod
    def from_row(
        cls,
        skill: Skill,
        definition: BuiltInSkillDefinition,
        db_session: Session,
    ) -> "BuiltinSkillResponse":
        return cls(
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            is_available=definition.is_available(db_session),
            unavailable_reason=definition.unavailable_reason,
        )


class CustomSkillResponse(BaseModel):
    source: Literal["custom"] = "custom"
    id: UUID
    slug: str
    name: str
    description: str
    is_public: bool
    enabled: bool
    author_user_id: UUID | None = None
    author_email: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    granted_group_ids: list[int] = []
    is_personal: bool

    @classmethod
    def from_model(
        cls,
        skill: Skill,
        group_ids: list[int],
        *,
        has_grants: bool | None = None,
    ) -> "CustomSkillResponse":
        # Paths that withhold group ids from the response (user-facing) must
        # still pass grant existence so grants-shared skills aren't marked
        # personal.
        grants_exist = bool(group_ids) if has_grants is None else has_grants
        is_personal = (
            skill.built_in_skill_id is None and not skill.is_public and not grants_exist
        )
        return cls(
            id=skill.id,
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            is_public=skill.is_public,
            enabled=skill.enabled,
            author_user_id=skill.author_user_id,
            author_email=skill.author.email if skill.author is not None else None,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            granted_group_ids=group_ids,
            is_personal=is_personal,
        )


class SkillsList(BaseModel):
    builtins: list[BuiltinSkillResponse]
    customs: list[CustomSkillResponse]


class SkillPatchRequest(BaseModel):
    is_public: bool | None = None
    enabled: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: Any) -> Any:
        """Omitting a field = 'leave unchanged'. Sending null = invalid."""
        if isinstance(data, dict):
            for field in ("is_public", "enabled"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return data

    def to_domain(self) -> SkillPatch:
        return SkillPatch(**{f: getattr(self, f) for f in self.model_fields_set})


class PersonalSkillPatchRequest(BaseModel):
    """User-endpoint patch: ``enabled`` only. ``is_public`` is the promotion
    seam and stays admin-only."""

    enabled: bool


class GrantsReplace(BaseModel):
    group_ids: list[int]
