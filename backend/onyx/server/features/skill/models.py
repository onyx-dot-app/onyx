"""Pydantic request and response models for the skills API."""

import datetime
from dataclasses import replace
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from onyx.db.enums import (
    PluginInstallationPolicy,
    SkillAccessLevel,
    SkillSharePermission,
)
from onyx.db.models import Skill
from onyx.db.plugin_access import PluginAccess
from onyx.db.skill import SkillSharingChange
from onyx.db.utils import UNSET
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.models import GITHUB_SKILL_MAX_COUNT, SkillBundleFile
from onyx.utils.github import GITHUB_COMMIT_SHA_PATTERN


class SkillUserShare(BaseModel):
    user: MinimalUserSnapshot
    permission: SkillSharePermission


class SkillGroupShare(BaseModel):
    group_id: int
    group_name: str
    permission: SkillSharePermission


class SkillExternalAppDependencyResponse(BaseModel):
    external_app_id: int
    name: str
    enabled: bool
    ready: bool


class SkillResponse(BaseModel):
    source: Literal["builtin", "custom"]
    id: UUID
    name: str
    description: str

    is_available: bool | None = None
    unavailable_reason: str | None = None
    is_valid: bool | None = None

    enabled: bool
    can_toggle: bool
    # The skill's own company setting. None: it follows the default of its
    # marketplace. Built-ins report AVAILABLE.
    installation_policy: PluginInstallationPolicy | None = None
    # The default of the skill's marketplace. None for built-ins.
    default_installation_policy: PluginInstallationPolicy | None = None
    # The caller can delete the skill (``may_delete_skill``, and they can
    # edit it).
    can_delete: bool = False
    # The setting for the current user is REQUIRED, from the company setting
    # or one of their groups.
    required_for_user: bool = False
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
    external_app: SkillExternalAppDependencyResponse | None = None
    # The plugin version of a custom skill whose files this response shows.
    # Edits send it back as base_version_id. None for built-ins.
    current_version_id: UUID | None = None
    current_version_number: int | None = None
    # The version the organization runs. None while the skill is private.
    published_version_number: int | None = None
    # The version that waits for an admin's review, if any.
    pending_version_number: int | None = None

    @classmethod
    def from_builtin(
        cls,
        skill: Skill,
        definition: BuiltInSkillDefinition,
        db_session: Session,
        enabled: bool,
        can_toggle: bool,
        external_app: SkillExternalAppDependencyResponse | None = None,
    ) -> "SkillResponse":
        return cls(
            source="builtin",
            id=skill.id,
            name=skill.name,
            description=skill.description,
            is_available=definition.is_available(db_session),
            unavailable_reason=definition.unavailable_reason,
            enabled=enabled,
            can_toggle=can_toggle,
            installation_policy=PluginInstallationPolicy.AVAILABLE,
            user_permission=SkillAccessLevel.VIEWER,
            external_app=external_app,
        )

    @classmethod
    def from_custom(
        cls,
        skill: Skill,
        access: PluginAccess | None,
        *,
        enabled: bool,
        can_toggle: bool = True,
        required_for_user: bool = False,
        user_permission: SkillAccessLevel | None = None,
        can_delete: bool = False,
        include_share_details: bool = False,
        external_app: SkillExternalAppDependencyResponse | None = None,
        current_version_id: UUID | None = None,
    ) -> "SkillResponse":
        """Access fields come from the skill's plugin; ``access`` is None only
        for a custom skill with no plugin, which no one but an admin sees."""
        user_shares = [
            SkillUserShare(
                user=MinimalUserSnapshot(id=share.user_id, email=share.email),
                permission=share.permission,
            )
            for share in (access.user_shares if access is not None else ())
        ]
        group_shares = [
            SkillGroupShare(
                group_id=share.group_id,
                group_name=share.group_name,
                permission=share.permission,
            )
            for share in (access.group_shares if access is not None else ())
        ]
        author_user_id = access.author_user_id if access is not None else None
        author_email = access.author_email if access is not None else None
        published = access is not None and access.published
        return cls(
            source="custom",
            id=skill.id,
            name=(access.name if access is not None else None) or skill.name,
            description=(
                access.description if access is not None else skill.description
            ),
            is_valid=access.is_valid if access is not None else None,
            installation_policy=(
                access.installation_policy if access is not None else None
            ),
            default_installation_policy=(
                access.marketplace_default_policy if access is not None else None
            ),
            can_delete=can_delete,
            required_for_user=required_for_user,
            enabled=enabled,
            can_toggle=can_toggle,
            author_user_id=author_user_id,
            author_email=author_email,
            owner=(
                MinimalUserSnapshot(id=author_user_id, email=author_email)
                if author_user_id is not None and author_email is not None
                else None
            ),
            ownership_vacant=author_email is None
            or access is None
            or not access.author_is_active,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            user_shares=user_shares if include_share_details else [],
            group_shares=group_shares if include_share_details else [],
            public_permission=SkillSharePermission.VIEWER if published else None,
            is_personal=not published and not user_shares and not group_shares,
            user_permission=user_permission,
            external_app=external_app,
            current_version_id=current_version_id,
            current_version_number=(
                access.current_version_number if access is not None else None
            ),
            published_version_number=(
                access.published_version_number if access is not None else None
            ),
            pending_version_number=(
                access.pending_version_number if access is not None else None
            ),
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
    external_app: SkillExternalAppDependencyResponse | None = None

    @classmethod
    def from_builtin(
        cls,
        skill: Skill,
        *,
        instructions_markdown: str,
        external_app: SkillExternalAppDependencyResponse | None = None,
    ) -> "SkillPreviewResponse":
        return cls(
            source="builtin",
            id=skill.id,
            name=skill.name,
            description=skill.description,
            author_email=None,
            instructions_markdown=instructions_markdown,
            external_app=external_app,
        )

    @classmethod
    def from_custom(
        cls,
        skill: Skill,
        access: PluginAccess | None,
        *,
        instructions_markdown: str,
        external_app: SkillExternalAppDependencyResponse | None = None,
    ) -> "SkillPreviewResponse":
        return cls(
            source="custom",
            id=skill.id,
            name=(access.name if access is not None else None) or skill.name,
            description=(
                access.description if access is not None else skill.description
            ),
            author_email=access.author_email if access is not None else None,
            instructions_markdown=instructions_markdown,
            external_app=external_app,
        )


class SkillEditableDetailResponse(SkillResponse):
    instructions_markdown: str
    files: list[SkillBundleFile]


class SkillVersionResponse(BaseModel):
    id: UUID
    version_number: int
    created_at: datetime.datetime
    created_by_email: str | None
    is_current: bool
    review_status: Literal["draft", "pending", "published"]


class SkillVersionPreviewResponse(BaseModel):
    description: str
    instructions_markdown: str


class SkillVersionRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The current version the restore starts from. 409 when it is not current.
    base_version_id: UUID


class SkillPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The current version the user saw. 409 when it is not current.
    base_version_id: UUID | None = None


class SkillReviewRequestResponse(BaseModel):
    skill_id: UUID
    name: str | None
    version_id: UUID
    version_number: int
    # None for a first publish.
    published_version_number: int | None
    # The skill's author: only the author or a manager publishes.
    author_email: str | None
    version_created_at: datetime.datetime


class SkillBundleInspectResponse(BaseModel):
    name: str
    description: str
    instructions_markdown: str
    files: list[SkillBundleFile]


class GitHubSkillPreview(BaseModel):
    path: str
    name: str
    description: str | None
    unavailable_reason: str | None


class GitHubSkillsPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str


class GitHubSkillsPreviewResponse(BaseModel):
    repository: str
    revision: str
    subpath: str | None
    skills: list[GitHubSkillPreview]


class GitHubSkillsImportRequest(GitHubSkillsPreviewRequest):
    revision: str = Field(pattern=GITHUB_COMMIT_SHA_PATTERN)
    subpath: str | None = None
    paths: list[str] = Field(min_length=1, max_length=GITHUB_SKILL_MAX_COUNT)
    sharing: "SkillShareRequest | None" = None


class GitHubImportedSkill(BaseModel):
    skill: SkillResponse
    disabled_reason: str | None = None


class GitHubSkillNotImported(BaseModel):
    path: str
    name: str
    reason: str


class GitHubSkillsImportResponse(BaseModel):
    imported: list[GitHubImportedSkill]
    not_imported: list[GitHubSkillNotImported]


class OrganizationLibraryDefaultAccess(BaseModel):
    """The install setting of every published skill with no own setting."""

    installation_policy: PluginInstallationPolicy


class SkillEnableRequest(BaseModel):
    enabled: bool
    replace_conflict: bool = False


class SkillCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    instructions_markdown: str

    @model_validator(mode="after")
    def _strip_values(self) -> "SkillCreateRequest":
        for field in ("name", "description", "instructions_markdown"):
            stripped = getattr(self, field).strip()  # ods: ignore[getattr]
            if not stripped:
                raise ValueError(f"{field} cannot be empty")
            setattr(self, field, stripped)
        return self


class SkillPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    instructions_markdown: str | None = None
    public_permission: SkillSharePermission | None = None
    # The plugin version the edit starts from. When it is not the newest
    # version, a details update is refused with 409. Omit to skip the check.
    base_version_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data: Any) -> Any:
        """Omitting a field = 'leave unchanged'. Null is invalid for these
        fields; null ``public_permission`` is valid and revokes org access."""
        if isinstance(data, dict):
            for field in (
                "description",
                "instructions_markdown",
            ):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return data

    @model_validator(mode="after")
    def _strip_values(self) -> "SkillPatchRequest":
        for field in ("description", "instructions_markdown"):
            value = getattr(self, field)  # ods: ignore[getattr]
            if value is None:
                continue
            stripped = value.strip()
            if not stripped:
                raise ValueError(f"{field} cannot be empty")
            setattr(self, field, stripped)
        return self

    @property
    def has_details_update(self) -> bool:
        return bool(self.model_fields_set & {"description", "instructions_markdown"})

    @property
    def has_db_field_update(self) -> bool:
        return "public_permission" in self.model_fields_set


class SkillUserShareRequest(BaseModel):
    user_id: UUID
    permission: SkillSharePermission


class SkillGroupSettingRequest(BaseModel):
    group_id: int
    # Null: the group follows the company setting.
    installation_policy: PluginInstallationPolicy | None


class SkillGroupShareRequest(BaseModel):
    group_id: int
    permission: SkillSharePermission


class SkillBulkSharing(BaseModel):
    """An access change for many skills. Group install settings are set one
    skill at a time (``SkillShareRequest``)."""

    model_config = ConfigDict(extra="forbid")

    # Missing: unchanged. Null: no own setting, so the marketplace default
    # applies. A value, AVAILABLE too, is the skill's own setting.
    installation_policy: PluginInstallationPolicy | None = None

    user_shares: list[SkillUserShareRequest] | None = None
    group_shares: list[SkillGroupShareRequest] | None = None
    public_permission: SkillSharePermission | None = None

    def to_change(self) -> SkillSharingChange:
        return SkillSharingChange(
            public_permission=self.public_permission,
            set_public_permission="public_permission" in self.model_fields_set,
            installation_policy=(
                self.installation_policy
                if "installation_policy" in self.model_fields_set
                else UNSET
            ),
            user_shares=(
                {share.user_id: share.permission for share in self.user_shares}
                if self.user_shares is not None
                else None
            ),
            group_shares=(
                {share.group_id: share.permission for share in self.group_shares}
                if self.group_shares is not None
                else None
            ),
        )


class SkillShareRequest(SkillBulkSharing):
    # Group install settings with no change to the group's share. A group with
    # no row gets a row that holds only the setting.
    group_settings: list[SkillGroupSettingRequest] | None = None

    def to_change(self) -> SkillSharingChange:
        if self.group_settings is None:
            return super().to_change()
        return replace(
            super().to_change(),
            group_settings={
                setting.group_id: setting.installation_policy
                for setting in self.group_settings
            },
        )


class TransferSkillOwnershipRequest(BaseModel):
    new_owner_user_id: UUID


class SkillBulkShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_ids: list[UUID] = Field(min_length=1, max_length=GITHUB_SKILL_MAX_COUNT)
    action: Literal["share"]
    sharing: SkillBulkSharing


class SkillBulkActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_ids: list[UUID] = Field(min_length=1, max_length=GITHUB_SKILL_MAX_COUNT)
    action: Literal["enable", "disable", "delete"]


class SkillBulkFailure(BaseModel):
    skill_id: UUID
    detail: str


class SkillBulkResponse(BaseModel):
    succeeded: list[UUID]
    failed: list[SkillBulkFailure]
