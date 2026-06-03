from datetime import datetime
from typing import Any
from typing import TYPE_CHECKING
from typing import Union

from pydantic import BaseModel

from onyx.configs.constants import MessageType
from onyx.db.enums import ArtifactType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SharingScope
from onyx.server.features.build.sandbox.models import FilesystemEntry as FileSystemEntry

if TYPE_CHECKING:
    from onyx.db.models import BuildSession
    from onyx.db.models import Sandbox


# ===== Session Models =====
class SessionCreateRequest(BaseModel):
    """Request to create a new build session."""

    name: str | None = None  # Optional session name
    # LLM selection from user's cookie
    llm_provider_type: str | None = None  # Provider type (e.g., "anthropic", "openai")
    llm_model_name: str | None = None  # Model name (e.g., "claude-opus-4-5")
    # Skip Next.js dev server startup. Used by integration tests that don't
    # exercise the webapp proxy and don't want to pay the ~20s startup wait.
    headless: bool = False


class SessionUpdateRequest(BaseModel):
    """Request to update a build session.

    If name is None, the session name will be auto-generated using LLM.
    """

    name: str | None = None


class SessionNameGenerateResponse(BaseModel):
    """Response containing a generated session name."""

    name: str


class SandboxResponse(BaseModel):
    """Sandbox metadata in session response."""

    id: str
    status: SandboxStatus
    container_id: str | None
    created_at: datetime
    last_heartbeat: datetime | None

    @classmethod
    def from_model(cls, sandbox: Any) -> "SandboxResponse":
        """Convert Sandbox ORM model to response."""
        return cls(
            id=str(sandbox.id),
            status=sandbox.status,
            container_id=sandbox.container_id,
            created_at=sandbox.created_at,
            last_heartbeat=sandbox.last_heartbeat,
        )


class ArtifactResponse(BaseModel):
    """Artifact metadata in session response."""

    id: str
    session_id: str
    type: ArtifactType
    name: str
    path: str
    preview_url: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, artifact: Any) -> "ArtifactResponse":
        """Convert Artifact ORM model to response."""
        return cls(
            id=str(artifact.id),
            session_id=str(artifact.session_id),
            type=artifact.type,
            name=artifact.name,
            path=artifact.path,
            preview_url=getattr(artifact, "preview_url", None),
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )


class SessionResponse(BaseModel):
    """Response containing session details."""

    id: str
    user_id: str | None
    name: str | None
    status: BuildSessionStatus
    created_at: datetime
    last_activity_at: datetime
    nextjs_port: int | None
    sandbox: SandboxResponse | None
    artifacts: list[ArtifactResponse]
    sharing_scope: SharingScope
    agent_provider: str | None
    agent_model: str | None

    @classmethod
    def from_model(
        cls, session: "BuildSession", sandbox: Union["Sandbox", None] = None
    ) -> "SessionResponse":
        """Convert BuildSession ORM model to response.

        Args:
            session: BuildSession ORM model
            sandbox: Optional Sandbox ORM model. Since sandboxes are now user-owned
                     (not session-owned), the sandbox must be passed separately.
        """
        return cls(
            id=str(session.id),
            user_id=str(session.user_id) if session.user_id else None,
            name=session.name,
            status=session.status,
            created_at=session.created_at,
            last_activity_at=session.last_activity_at,
            nextjs_port=session.nextjs_port,
            sandbox=(SandboxResponse.from_model(sandbox) if sandbox else None),
            artifacts=[ArtifactResponse.from_model(a) for a in session.artifacts],
            sharing_scope=session.sharing_scope,
            agent_provider=session.agent_provider,
            agent_model=session.agent_model,
        )


class DetailedSessionResponse(SessionResponse):
    """Extended session response with sandbox state details.

    Used for single-session endpoints where we compute expensive fields
    like session_loaded_in_sandbox.
    """

    session_loaded_in_sandbox: bool

    @classmethod
    def from_session_response(
        cls,
        base: SessionResponse,
        session_loaded_in_sandbox: bool,
    ) -> "DetailedSessionResponse":
        return cls(
            **base.model_dump(),
            session_loaded_in_sandbox=session_loaded_in_sandbox,
        )


class SessionListResponse(BaseModel):
    """Response containing list of sessions."""

    sessions: list[SessionResponse]


class SetSessionSharingRequest(BaseModel):
    """Request to set the sharing scope of a session."""

    sharing_scope: SharingScope


class SetSessionSharingResponse(BaseModel):
    """Response after setting session sharing scope."""

    session_id: str
    sharing_scope: SharingScope


# ===== Message Models =====
class MessageRequest(BaseModel):
    """Request to send a message to the CLI agent."""

    content: str
    # Per-message model override from the composer; both set together.
    provider: str | None = None
    model: str | None = None


class MessageInterruptResponse(BaseModel):
    """Response to an interrupt request. ``interrupted`` is False when there was
    no directly-interruptible turn (no running sandbox or no opencode session);
    the interrupt fence is set regardless."""

    interrupted: bool


class MessageResponse(BaseModel):
    """Response containing message details.

    All message data is stored in message_metadata as JSON (the raw sandbox event packet).
    The turn_index groups all assistant responses under the user prompt they respond to.

    Packet types in message_metadata:
    - user_message: {type: "user_message", content: {...}}
    - agent_message: {type: "agent_message", content: {...}}
    - agent_thought: {type: "agent_thought", content: {...}}
    - tool_call_progress: {type: "tool_call_progress", status: "completed", ...}
    - agent_plan_update: {type: "agent_plan_update", entries: [...]}
    """

    id: str
    session_id: str
    turn_index: int
    type: MessageType
    message_metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, message: Any) -> "MessageResponse":
        """Convert BuildMessage ORM model to response."""
        return cls(
            id=str(message.id),
            session_id=str(message.session_id),
            turn_index=message.turn_index,
            type=message.type,
            message_metadata=message.message_metadata,
            created_at=message.created_at,
        )


class MessageListResponse(BaseModel):
    """Response containing list of messages."""

    messages: list[MessageResponse]


# ===== Legacy Models (for compatibility with other code) =====
class CreateSessionRequest(BaseModel):
    task: str
    available_sources: list[str] | None = None


class CreateSessionResponse(BaseModel):
    session_id: str


class ExecuteRequest(BaseModel):
    task: str
    context: str | None = None


class ArtifactInfo(BaseModel):
    artifact_type: str  # "webapp", "file", "markdown", "image"
    path: str
    filename: str
    mime_type: str | None = None


class SessionStatus(BaseModel):
    session_id: str
    status: str  # "idle", "running", "completed", "failed"
    webapp_url: str | None = None


class DirectoryListing(BaseModel):
    path: str  # Current directory path
    entries: list[FileSystemEntry]  # Contents


class WebappInfo(BaseModel):
    has_webapp: bool  # Whether a webapp exists in outputs/web
    webapp_url: str | None  # URL to access the webapp (e.g., http://localhost:3015)
    status: str  # Sandbox status (running, terminated, etc.)
    ready: bool  # Whether the NextJS dev server is actually responding
    sharing_scope: SharingScope


# ===== File Upload Models =====
class UploadResponse(BaseModel):
    """Response after successful file upload."""

    filename: str  # Sanitized filename
    path: str  # Relative path in sandbox (e.g., "attachments/doc.pdf")
    size_bytes: int  # File size in bytes


# ===== Rate Limit Models =====
class RateLimitResponse(BaseModel):
    """Rate limit information."""

    is_limited: bool
    limit_type: str  # "weekly" or "total"
    messages_used: int
    limit: int
    reset_timestamp: str | None = None


# ===== Pre-Provisioned Session Check Models =====
class PreProvisionedCheckResponse(BaseModel):
    """Response for checking if a pre-provisioned session is still valid (empty)."""

    valid: bool  # True if session exists and has no messages
    session_id: str | None = None  # Session ID if valid, None otherwise


class PptxPreviewResponse(BaseModel):
    """Response with PPTX slide preview metadata."""

    slide_count: int
    slide_paths: list[str]  # Relative paths to slide JPEGs within session workspace
    cached: bool  # Whether result was served from cache


# ===== External App Models =====
class CreateBuiltInExternalAppRequest(BaseModel):
    """Create a built-in external app (``POST /admin/apps/built-in``).

    Built-in providers only — ``app_type=CUSTOM`` is rejected (custom apps use
    ``POST /admin/apps/custom``). Updates go through ``PATCH /admin/apps/{id}``.

    A new row is inserted (and a backing ``Skill`` row is created in the same
    transaction). ``upstream_url_patterns`` is a list of regex patterns matched
    by the egress proxy against outbound request URLs. ``enabled`` (stored on
    the linked skill) is the kill switch the proxy checks before injecting
    credentials.

    Skill identity (slug, bundle bytes, sharing scope) is derived server-side
    from ``app_type``; admins don't supply it.
    """

    name: str
    description: str
    enabled: bool
    app_type: ExternalAppType
    upstream_url_patterns: list[str]
    auth_template: dict[str, Any]
    organization_credentials: dict[str, str]
    # Map full-replaces stored overrides (empty clears); None defaults every
    # action. Keyed by catalog action id; validated on create.
    action_policies: dict[str, EndpointPolicy] | None = None


class UpdateExternalAppRequest(BaseModel):
    """Partial update of an existing app, keyed solely by the path ``id``
    (``PATCH /admin/apps/{id}``). Every field is optional; ``None`` means "leave
    untouched", so a narrow request (e.g. just ``enabled``) won't blank the rest.

    This is the single update path for built-in apps. For Onyx-managed built-ins
    (cloud) the gateway-config fields (``upstream_url_patterns``,
    ``auth_template``, ``organization_credentials``) are Onyx-owned and ignored —
    only ``enabled`` + ``action_policies`` take effect. Custom-app field edits
    (and bundle replacement) go through ``POST /admin/apps/custom`` instead, since
    that path is multipart.
    """

    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    upstream_url_patterns: list[str] | None = None
    auth_template: dict[str, Any] | None = None
    organization_credentials: dict[str, str] | None = None
    # Full-replace stored overrides when present (empty clears); None leaves them.
    action_policies: dict[str, EndpointPolicy] | None = None


class ActionPolicyView(BaseModel):
    """One action of a built-in app, with its effective policy — the admin's
    stored override if set, otherwise the action's ``default_policy``."""

    action_id: str
    normalised_name: str
    description: str
    state: EndpointPolicy


class ExternalAppAdminResponse(BaseModel):
    """Admin-facing view of an external app (includes org credentials)."""

    id: int
    name: str
    description: str
    app_type: ExternalAppType
    upstream_url_patterns: list[str]
    auth_template: dict[str, Any]
    organization_credentials: dict[str, Any]
    enabled: bool
    # The merged per-action policy view (built-in apps; empty for custom).
    actions: list[ActionPolicyView]
    # Onyx-managed built-in (cloud): creds/config Onyx-owned and blanked above;
    # admin may only enable/disable + set policies. UI hides the rest.
    is_onyx_managed: bool = False


class UpsertUserCredentialsRequest(BaseModel):
    """User-supplied credentials for a specific external app."""

    user_credentials: dict[str, Any]


class ExternalAppUserResponse(BaseModel):
    """User-facing view of an external app.

    `credential_keys` are the parameter names the calling user must supply —
    derived from the app's `auth_template` minus whatever the organization
    has already filled in. `credential_values` are the values the user has
    previously stored for those keys (intersection — stale keys from
    deleted/migrated templates are filtered out). `authenticated` is true
    iff `credential_values` covers every key in `credential_keys`.

    Admin-only fields (``organization_credentials``, ``auth_template``,
    ``upstream_url_patterns``, ``enabled``) are intentionally omitted.
    ``app_type`` is included — it's the non-sensitive provider
    discriminator the UI needs to render the app.
    """

    id: int
    name: str
    description: str
    slug: str
    app_type: ExternalAppType
    credential_keys: list[str]
    credential_values: dict[str, Any]
    authenticated: bool


class OAuthStartResponse(BaseModel):
    authorize_url: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class OAuthCallbackResponse(BaseModel):
    success: bool
    external_app_id: int


class OrgCredentialFieldDescriptor(BaseModel):
    """One credential field the admin must fill in to configure a
    built-in provider."""

    key: str
    label: str
    description: str
    secret: bool


class EndpointDescriptor(BaseModel):
    """One action in a built-in provider's catalog, flattened for the admin UI.
    The admin picks a policy per action; recognition rules stay backend-side."""

    action_id: str
    normalised_name: str
    description: str
    # The policy a new app's instance of this action defaults to; the create
    # form seeds each action's selector with it (the admin can still override).
    default_policy: EndpointPolicy


class BuiltInExternalAppDescriptor(BaseModel):
    """Backend-defined preset for a built-in OAuth provider. The admin
    UI fetches these and uses them to render the Configure modal +
    POST body, so adding a new provider is a backend-only change."""

    app_type: ExternalAppType
    name: str
    description: str
    upstream_url_patterns: list[str]
    auth_template: dict[str, str]
    required_org_credential_fields: list[OrgCredentialFieldDescriptor]
    setup_instructions: str
    # The catalog of actions an admin can govern (empty for providers without
    # a catalog).
    actions: list[EndpointDescriptor]
