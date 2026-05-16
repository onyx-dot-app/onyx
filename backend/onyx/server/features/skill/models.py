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
from onyx.skills.registry import BuiltinSkill


class BuiltinSkillResponse(BaseModel):
    source: Literal["builtin"] = "builtin"
    slug: str
    name: str
    description: str
    is_available: bool
    unavailable_reason: str | None = None

    @classmethod
    def from_builtin(
        cls, skill: BuiltinSkill, db_session: Session
    ) -> "BuiltinSkillResponse":
        return cls(
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            is_available=skill.is_available(db_session),
            unavailable_reason=skill.unavailable_reason,
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
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    granted_group_ids: list[int] = []

    @classmethod
    def from_model(cls, skill: Skill, group_ids: list[int]) -> "CustomSkillResponse":
        return cls(
            id=skill.id,
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            is_public=skill.is_public,
            enabled=skill.enabled,
            author_user_id=skill.author_user_id,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            granted_group_ids=group_ids,
        )


class SkillsList(BaseModel):
    builtins: list[BuiltinSkillResponse]
    customs: list[CustomSkillResponse]


class SkillPatchRequest(BaseModel):
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None
    enabled: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: Any) -> Any:
        """Omitting a field = 'leave unchanged'. Sending null = invalid."""
        if isinstance(data, dict):
            for field in ("slug", "name", "description", "is_public", "enabled"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return data

    def to_domain(self) -> SkillPatch:
        return SkillPatch(**{f: getattr(self, f) for f in self.model_fields_set})


class GrantsReplace(BaseModel):
    group_ids: list[int]
