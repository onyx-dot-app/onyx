"""Pydantic request and response models for the skills API."""

import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MarketplaceKind,
    PluginInstallationPolicy,
    SkillAccessLevel,
    SkillSharePermission,
)
from onyx.db.models import Plugin, Skill
from onyx.db.plugin_access import PluginAccess
from onyx.db.skill import SkillSharingChange
from onyx.db.utils import UNSET
from onyx.integrations.models import NeedCounts, PluginNeedView
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.models import (
    GITHUB_SKILL_MAX_COUNT,
    PluginManifest,
    SkillBundleFile,
    UserPastWriteLimit,
)


class SkillUserShare(BaseModel):
    user: MinimalUserSnapshot
    permission: SkillSharePermission


class SkillGroupShare(BaseModel):
    group_id: int
    group_name: str
    permission: SkillSharePermission


class SkillGroupSummary(BaseModel):
    """One group row of a skill: a share, a group install setting, or both."""

    group_id: int
    group_name: str
    # None for a row that holds only a setting.
    permission: SkillSharePermission | None
    # None: the group uses the company setting.
    installation_policy: PluginInstallationPolicy | None


class PluginSkillSummary(BaseModel):
    path: str
    name: str
    description: str


class PluginDetail(BaseModel):
    manifest: PluginManifest | None
    skills: list[PluginSkillSummary]
    needs: list[PluginNeedView]


class SkillMarketplace(BaseModel):
    id: UUID
    name: str
    kind: MarketplaceKind
    repository: str | None
    # A personal GitHub marketplace: only its owner gets the plugin.
    personal: bool


class SkillResponse(BaseModel):
    source: Literal["builtin", "custom"]
    id: UUID
    name: str
    description: str
    kind: Literal["skill", "plugin"] = "skill"
    available_count: int = 0
    needed_count: int = 0
    plugin: PluginDetail | None = None

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
    # Every group row the caller may see, with its setting.
    group_summaries: list[SkillGroupSummary] = Field(default_factory=list)
    public_permission: SkillSharePermission | None = None
    is_personal: bool = False
    user_permission: SkillAccessLevel | None = None
    # False for a skill that an organization-wide manager sees only through
    # that permission. The member pages leave it out.
    member_visible: bool = True
    # The user turned the skill on, but these skills hold one of its names.
    name_held_by: list[str] = Field(default_factory=list)
    # The plugin version of a custom skill whose files this response shows.
    # Edits send it back as base_version_id. None for built-ins.
    current_version_id: UUID | None = None
    current_version_number: int | None = None
    # The version the organization runs. None while the skill is private.
    published_version_number: int | None = None
    # The version that waits for an admin's review, if any.
    pending_version_number: int | None = None
    marketplace: SkillMarketplace | None = None
    content_locked: bool = False

    @classmethod
    def from_builtin(
        cls,
        skill: Skill,
        definition: BuiltInSkillDefinition,
        db_session: Session,
        enabled: bool,
        can_toggle: bool,
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
        )

    @classmethod
    def from_custom(
        cls,
        plugin: Plugin,
        access: PluginAccess,
        *,
        enabled: bool,
        can_toggle: bool = True,
        required_for_user: bool = False,
        name_held_by: list[str] | None = None,
        user_permission: SkillAccessLevel | None = None,
        can_delete: bool = False,
        include_share_details: bool = False,
        group_summaries: list[SkillGroupSummary] | None = None,
        current_version_id: UUID | None = None,
        counts: NeedCounts | None = None,
        plugin_detail: PluginDetail | None = None,
    ) -> "SkillResponse":
        """Every field comes from the skill's plugin."""
        user_shares = [
            SkillUserShare(
                user=MinimalUserSnapshot(id=share.user_id, email=share.email),
                permission=share.permission,
            )
            for share in access.user_shares
        ]
        group_shares = [
            SkillGroupShare(
                group_id=share.group_id,
                group_name=share.group_name,
                permission=share.permission,
            )
            for share in access.group_shares
        ]
        return cls(
            source="custom",
            id=plugin.id,
            name=access.name or plugin.name,
            description=access.description,
            kind="skill" if access.is_skill else "plugin",
            available_count=counts.available_count if counts is not None else 0,
            needed_count=counts.needed_count if counts is not None else 0,
            plugin=plugin_detail,
            is_valid=access.is_valid,
            installation_policy=access.installation_policy,
            default_installation_policy=access.marketplace_default_policy,
            can_delete=can_delete,
            required_for_user=required_for_user,
            name_held_by=name_held_by or [],
            enabled=enabled,
            can_toggle=can_toggle,
            author_user_id=access.author_user_id,
            author_email=access.author_email,
            owner=(
                MinimalUserSnapshot(id=access.author_user_id, email=access.author_email)
                if access.author_user_id is not None and access.author_email is not None
                else None
            ),
            ownership_vacant=access.author_email is None or not access.author_is_active,
            created_at=plugin.created_at,
            updated_at=plugin.updated_at,
            user_shares=user_shares if include_share_details else [],
            group_shares=group_shares if include_share_details else [],
            group_summaries=group_summaries or [],
            public_permission=SkillSharePermission.VIEWER if access.published else None,
            is_personal=not access.published and not user_shares and not group_shares,
            user_permission=user_permission,
            current_version_id=current_version_id,
            current_version_number=access.current_version_number,
            published_version_number=access.published_version_number,
            pending_version_number=access.pending_version_number,
            marketplace=SkillMarketplace(
                id=access.marketplace_id,
                name=access.marketplace_name,
                kind=access.marketplace_kind,
                repository=access.marketplace_repository,
                personal=access.synced and access.marketplace_owner_user_id is not None,
            ),
            content_locked=access.synced,
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
    # The supporting files of the version the user runs; empty for a built-in.
    files: list[SkillBundleFile] = []

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
        plugin: Plugin,
        access: PluginAccess,
        *,
        instructions_markdown: str,
        files: list[SkillBundleFile],
    ) -> "SkillPreviewResponse":
        return cls(
            source="custom",
            id=plugin.id,
            name=access.name or plugin.name,
            description=access.description,
            author_email=access.author_email,
            instructions_markdown=instructions_markdown,
            files=files,
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
    # The version in plugin.json, for a plugin version that has one.
    manifest_version: str | None = None


class SkillVersionPreviewResponse(BaseModel):
    description: str
    # Empty for a plugin version, which has no root SKILL.md.
    instructions_markdown: str
    files: list[SkillBundleFile] = Field(default_factory=list)
    plugin: PluginDetail | None = None


class PluginSkillInstructions(BaseModel):
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


class PluginUploadSkill(BaseModel):
    path: str
    name: str
    description: str
    warnings: list[str]


class PluginUploadTarget(BaseModel):
    kind: Literal["new_version", "new_plugin"]
    plugin_id: UUID | None
    plugin_name: str
    version_number: int


class PluginUploadPreview(BaseModel):
    manifest: PluginManifest
    skills: list[PluginUploadSkill]
    needs: list[PluginNeedView]
    warnings: list[str]
    target: PluginUploadTarget
    # The plugin is on for the user after a save.
    will_enable: bool
    # The skills and plugins that keep a new plugin off: they hold one of
    # its skill names.
    name_conflicts: list[str]


class PluginUploadResponse(BaseModel):
    target: PluginUploadTarget
    plugin: SkillResponse
    enabled: bool
    # The files equal the current version's files, so no version was added.
    unchanged: bool
    name_conflicts: list[str]


class SkillBundleInspectResponse(BaseModel):
    name: str
    description: str
    instructions_markdown: str
    files: list[SkillBundleFile]


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


class SkillLimitUsersResponse(BaseModel):
    """Active users past the write limit (``max_bytes`` or ``max_files``)."""

    max_bytes: int
    max_files: int
    users: list[UserPastWriteLimit]


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
        return (
            super()
            .to_change()
            .model_copy(
                update={
                    "group_settings": {
                        setting.group_id: setting.installation_policy
                        for setting in self.group_settings
                    }
                }
            )
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
