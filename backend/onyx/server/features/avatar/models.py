"""
Pydantic models for Avatar API endpoints.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.db.enums import AvatarPermissionRequestStatus
from onyx.db.enums import AvatarQueryMode
from onyx.db.models import Avatar
from onyx.db.models import AvatarPermissionRequest


# ============================================================================
# Avatar Models
# ============================================================================


class AvatarSnapshot(BaseModel):
    """Snapshot of an avatar for API responses."""

    id: int
    user_id: UUID
    user_email: str
    name: str | None
    description: str | None
    is_enabled: bool
    default_query_mode: AvatarQueryMode
    allow_accessible_mode: bool
    show_query_in_request: bool
    max_requests_per_day: int | None
    created_at: datetime

    @classmethod
    def from_model(cls, avatar: Avatar) -> "AvatarSnapshot":
        return AvatarSnapshot(
            id=avatar.id,
            user_id=avatar.user_id,
            user_email=avatar.user.email,
            name=avatar.name,
            description=avatar.description,
            is_enabled=avatar.is_enabled,
            default_query_mode=avatar.default_query_mode,
            allow_accessible_mode=avatar.allow_accessible_mode,
            show_query_in_request=avatar.show_query_in_request,
            max_requests_per_day=avatar.max_requests_per_day,
            created_at=avatar.created_at,
        )


class AvatarUpdateRequest(BaseModel):
    """Request to update avatar settings."""

    name: str | None = None
    description: str | None = None
    is_enabled: bool | None = None
    default_query_mode: AvatarQueryMode | None = None
    allow_accessible_mode: bool | None = None
    show_query_in_request: bool | None = None
    max_requests_per_day: int | None = None
    auto_approve_rules: dict | None = None


class AvatarListItem(BaseModel):
    """Minimal avatar info for listing queryable avatars."""

    id: int
    user_id: UUID
    user_email: str
    name: str | None
    description: str | None
    default_query_mode: AvatarQueryMode
    allow_accessible_mode: bool

    @classmethod
    def from_model(cls, avatar: Avatar) -> "AvatarListItem":
        return AvatarListItem(
            id=avatar.id,
            user_id=avatar.user_id,
            user_email=avatar.user.email,
            name=avatar.name,
            description=avatar.description,
            default_query_mode=avatar.default_query_mode,
            allow_accessible_mode=avatar.allow_accessible_mode,
        )


# ============================================================================
# Avatar Query Models
# ============================================================================


class AvatarQueryRequest(BaseModel):
    """Request to query an avatar."""

    query: str
    query_mode: AvatarQueryMode = AvatarQueryMode.OWNED_DOCUMENTS
    chat_session_id: UUID | None = None


class AvatarQueryResponse(BaseModel):
    """Response from an avatar query."""

    status: (
        str  # "success", "pending_permission", "no_results", "rate_limited", "disabled"
    )
    answer: str | None = None
    permission_request_id: int | None = None
    source_document_ids: list[str] | None = None
    message: str | None = None


class BroadcastQueryRequest(BaseModel):
    """Request to query multiple avatars."""

    avatar_ids: list[int]
    query: str
    query_mode: AvatarQueryMode = AvatarQueryMode.OWNED_DOCUMENTS


class BroadcastQueryResponse(BaseModel):
    """Response from a broadcast query to multiple avatars."""

    results: dict[int, AvatarQueryResponse]  # avatar_id -> response


# ============================================================================
# Permission Request Models
# ============================================================================


class PermissionRequestSnapshot(BaseModel):
    """Snapshot of a permission request for API responses."""

    id: int
    avatar_id: int
    avatar_user_email: str
    requester_id: UUID
    requester_email: str
    query_text: str | None  # May be hidden based on avatar settings
    status: AvatarPermissionRequestStatus
    denial_reason: str | None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None

    @classmethod
    def from_model(
        cls,
        request: AvatarPermissionRequest,
        show_query: bool = True,
    ) -> "PermissionRequestSnapshot":
        return PermissionRequestSnapshot(
            id=request.id,
            avatar_id=request.avatar_id,
            avatar_user_email=request.avatar.user.email,
            requester_id=request.requester_id,
            requester_email=request.requester.email,
            query_text=request.query_text if show_query else None,
            status=request.status,
            denial_reason=request.denial_reason,
            created_at=request.created_at,
            expires_at=request.expires_at,
            resolved_at=request.resolved_at,
        )


class PermissionRequestDenyRequest(BaseModel):
    """Request to deny a permission request."""

    denial_reason: str | None = None


class PermissionRequestApproveResponse(BaseModel):
    """Response when a permission request is approved, including the cached answer."""

    request_id: int
    status: AvatarPermissionRequestStatus
    answer: str | None
    source_document_ids: list[int] | None


# ============================================================================
# Auto-Approve Rules Models
# ============================================================================


class AutoApproveRules(BaseModel):
    """Rules for auto-approving permission requests."""

    user_ids: list[str] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)
    all_users: bool = False
