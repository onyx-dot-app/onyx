"""Pydantic request and response models for the skills API."""

import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.db.enums import SkillAccessLevel
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.built_in import BuiltInSkillDefinition


class SkillUserShare(BaseModel):
    user: MinimalUserSnapshot
    permission: SkillSharePermission


class SkillGroupShare(BaseModel):
    group_id: int
    group_name: str
    permission: SkillSharePermission


class SkillResponse(BaseModel):
    source: Literal["builtin", "custom"]
    id: UUID
    slug: str
    name: str
    description: str

    is_available: bool | None = None
    unavailable_reason: str | None = None

    is_public: bool | None = None
    enabled: bool | None = None
    author_user_id: UUID | None = None
    author_email: str | None = None
    owner: MinimalUserSnapshot | None = None
    ownership_vacant: bool = False
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    user_shares: list[SkillUserShare] = Field(default_factory=list)
    group_shares: list[SkillGroupShare] = Field(default_factory=list)
    public_permission: SkillSharePermission | None = None
    is_personal: bool = False
    user_permission: SkillAccessLevel | None = None

    @classmethod
    def from_builtin(
        cls,
        skill: Skill,
        definition: BuiltInSkillDefinition,
        db_session: Session,
    ) -> "SkillResponse":
        return cls(
            source="builtin",
            id=skill.id,
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            is_available=definition.is_available(db_session),
            unavailable_reason=definition.unavailable_reason,
        )

    @classmethod
    def from_custom(
        cls,
        skill: Skill,
        *,
        user_permission: SkillAccessLevel | None = None,
        include_share_details: bool = False,
    ) -> "SkillResponse":
        user_shares = [
            SkillUserShare(
                user=MinimalUserSnapshot(id=share.user.id, email=share.user.email),
                permission=share.permission,
            )
            for share in skill.user_shares
            if share.user is not None
        ]
        group_shares = [
            SkillGroupShare(
                group_id=share.user_group_id,
                group_name=share.user_group.name,
                permission=share.permission,
            )
            for share in skill.group_shares
            if share.user_group is not None
        ]
        visible_user_shares = user_shares if include_share_details else []
        visible_group_shares = group_shares if include_share_details else []
        return cls(
            source="custom",
            id=skill.id,
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            is_public=skill.is_public,
            enabled=skill.enabled,
            author_user_id=skill.author_user_id,
            author_email=skill.author.email if skill.author is not None else None,
            owner=(
                MinimalUserSnapshot(id=skill.author.id, email=skill.author.email)
                if skill.author is not None
                else None
            ),
            ownership_vacant=skill.author_user_id is None
            or skill.author is None
            or not skill.author.is_active,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            user_shares=visible_user_shares,
            group_shares=visible_group_shares,
            public_permission=skill.public_permission,
            is_personal=not skill.is_public and not user_shares and not group_shares,
            user_permission=user_permission,
        )


class SkillsList(BaseModel):
    builtins: list[SkillResponse]
    customs: list[SkillResponse]


class SkillPreviewResponse(BaseModel):
    source: Literal["builtin", "custom"]
    id: UUID
    name: str
    description: str
    author_email: str | None = None
    instructions_markdown: str

    @classmethod
    def from_builtin(
        cls,
        skill: Skill,
        *,
        instructions_markdown: str,
    ) -> "SkillPreviewResponse":
        return cls(
            source="builtin",
            id=skill.id,
            name=skill.name,
            description=skill.description,
            author_email=None,
            instructions_markdown=instructions_markdown,
        )

    @classmethod
    def from_custom(
        cls,
        skill: Skill,
        *,
        instructions_markdown: str,
    ) -> "SkillPreviewResponse":
        return cls(
            source="custom",
            id=skill.id,
            name=skill.name,
            description=skill.description,
            author_email=skill.author.email if skill.author is not None else None,
            instructions_markdown=instructions_markdown,
        )


class SkillEditableDetailResponse(SkillResponse):
    instructions_markdown: str


class SkillPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    instructions_markdown: str | None = None
    is_public: bool | None = None
    public_permission: SkillSharePermission | None = None
    enabled: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: Any) -> Any:
        """Omitting a field = 'leave unchanged'. Sending null = invalid."""
        if isinstance(data, dict):
            for field in (
                "name",
                "description",
                "instructions_markdown",
                "is_public",
                "public_permission",
                "enabled",
            ):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return data

    @model_validator(mode="after")
    def _strip_values(self) -> "SkillPatchRequest":
        for field in ("name", "description", "instructions_markdown"):
            value = getattr(self, field)
            if value is None:
                continue
            stripped = value.strip()
            if not stripped:
                raise ValueError(f"{field} cannot be empty")
            setattr(self, field, stripped)
        return self

    @property
    def has_details_update(self) -> bool:
        return bool(
            self.model_fields_set & {"name", "description", "instructions_markdown"}
        )

    @property
    def has_db_field_update(self) -> bool:
        return bool(
            self.model_fields_set & {"is_public", "public_permission", "enabled"}
        )


class SkillUserShareRequest(BaseModel):
    user_id: UUID
    permission: SkillSharePermission


class SkillGroupShareRequest(BaseModel):
    group_id: int
    permission: SkillSharePermission


class SkillShareRequest(BaseModel):
    user_shares: list[SkillUserShareRequest] | None = None
    group_shares: list[SkillGroupShareRequest] | None = None
    is_public: bool | None = None
    public_permission: SkillSharePermission | None = None


class TransferSkillOwnershipRequest(BaseModel):
    new_owner_user_id: UUID
