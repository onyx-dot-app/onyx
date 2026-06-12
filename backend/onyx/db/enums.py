from __future__ import annotations

from enum import Enum as PyEnum
from typing import ClassVar


class AccountType(str, PyEnum):
    """
    What kind of account this is — determines whether the user
    enters the group-based permission system.

    STANDARD + SERVICE_ACCOUNT → participate in group system
    BOT, EXT_PERM_USER, ANONYMOUS → fixed behavior
    """

    STANDARD = "STANDARD"
    BOT = "BOT"
    EXT_PERM_USER = "EXT_PERM_USER"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"
    ANONYMOUS = "ANONYMOUS"

    def is_web_login(self) -> bool:
        """Whether this account type supports interactive web login."""
        return self not in (
            AccountType.BOT,
            AccountType.EXT_PERM_USER,
        )


class GrantSource(str, PyEnum):
    """How a permission grant was created."""

    USER = "USER"
    SCIM = "SCIM"
    SYSTEM = "SYSTEM"


class IndexingStatus(str, PyEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    CANCELED = "canceled"
    FAILED = "failed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"

    def is_terminal(self) -> bool:
        terminal_states = {
            IndexingStatus.SUCCESS,
            IndexingStatus.COMPLETED_WITH_ERRORS,
            IndexingStatus.CANCELED,
            IndexingStatus.FAILED,
        }
        return self in terminal_states

    def is_successful(self) -> bool:
        return (
            self == IndexingStatus.SUCCESS
            or self == IndexingStatus.COMPLETED_WITH_ERRORS
        )


class PermissionSyncStatus(str, PyEnum):
    """Status enum for permission sync attempts"""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    CANCELED = "canceled"
    FAILED = "failed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"

    def is_terminal(self) -> bool:
        terminal_states = {
            PermissionSyncStatus.SUCCESS,
            PermissionSyncStatus.COMPLETED_WITH_ERRORS,
            PermissionSyncStatus.CANCELED,
            PermissionSyncStatus.FAILED,
        }
        return self in terminal_states

    def is_successful(self) -> bool:
        return (
            self == PermissionSyncStatus.SUCCESS
            or self == PermissionSyncStatus.COMPLETED_WITH_ERRORS
        )


class PortAttemptStatus(str, PyEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

    def is_terminal(self) -> bool:
        return self in {
            PortAttemptStatus.SUCCESS,
            PortAttemptStatus.FAILED,
            PortAttemptStatus.CANCELED,
        }

    def is_successful(self) -> bool:
        return self == PortAttemptStatus.SUCCESS


class IndexingMode(str, PyEnum):
    UPDATE = "update"
    REINDEX = "reindex"


class ProcessingMode(str, PyEnum):
    """Determines how documents are processed after fetching."""

    REGULAR = "REGULAR"  # Full pipeline: chunk → embed → index
    FILE_SYSTEM = "FILE_SYSTEM"  # Deprecated: bypasses indexing, not searchable
    RAW_BINARY = "RAW_BINARY"  # Write raw binary to S3 (no text extraction)


class SyncType(str, PyEnum):
    DOCUMENT_SET = "document_set"
    USER_GROUP = "user_group"
    CONNECTOR_DELETION = "connector_deletion"
    PRUNING = "pruning"  # not really a sync, but close enough
    EXTERNAL_PERMISSIONS = "external_permissions"
    EXTERNAL_GROUP = "external_group"

    def __str__(self) -> str:
        return self.value


class SyncStatus(str, PyEnum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"

    def is_terminal(self) -> bool:
        terminal_states = {
            SyncStatus.SUCCESS,
            SyncStatus.FAILED,
        }
        return self in terminal_states


class MCPAuthenticationType(str, PyEnum):
    NONE = "NONE"
    API_TOKEN = "API_TOKEN"
    OAUTH = "OAUTH"
    PT_OAUTH = "PT_OAUTH"  # Pass-Through OAuth


class MCPOAuthProviderMode(str, PyEnum):
    AUTO_DISCOVERY = "AUTO_DISCOVERY"
    KNOWN_PROVIDER = "KNOWN_PROVIDER"


class MCPTransport(str, PyEnum):
    """MCP transport types"""

    STDIO = "STDIO"  # TODO: currently unsupported, need to add a user guide for setup
    SSE = "SSE"  # Server-Sent Events (deprecated but still used)
    STREAMABLE_HTTP = "STREAMABLE_HTTP"  # Modern HTTP streaming


class MCPAuthenticationPerformer(str, PyEnum):
    ADMIN = "ADMIN"
    PER_USER = "PER_USER"


class MCPServerStatus(str, PyEnum):
    CREATED = "CREATED"  # Server created, needs auth configuration
    AWAITING_AUTH = "AWAITING_AUTH"  # Auth configured, pending user authentication
    FETCHING_TOOLS = "FETCHING_TOOLS"  # Auth complete, fetching tools
    CONNECTED = "CONNECTED"  # Fully configured and connected
    DISCONNECTED = "DISCONNECTED"  # Server disconnected, but not deleted


# Consistent with Celery task statuses
class TaskStatus(str, PyEnum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class IndexModelStatus(str, PyEnum):
    PAST = "PAST"
    PRESENT = "PRESENT"
    FUTURE = "FUTURE"

    def is_current(self) -> bool:
        return self == IndexModelStatus.PRESENT

    def is_future(self) -> bool:
        return self == IndexModelStatus.FUTURE


class ChatSessionSharedStatus(str, PyEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class ConnectorCredentialPairStatus(str, PyEnum):
    SCHEDULED = "SCHEDULED"
    INITIAL_INDEXING = "INITIAL_INDEXING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETING = "DELETING"
    INVALID = "INVALID"

    @classmethod
    def active_statuses(cls) -> list["ConnectorCredentialPairStatus"]:
        return [
            ConnectorCredentialPairStatus.ACTIVE,
            ConnectorCredentialPairStatus.SCHEDULED,
            ConnectorCredentialPairStatus.INITIAL_INDEXING,
        ]

    @classmethod
    def indexable_statuses(self) -> list["ConnectorCredentialPairStatus"]:
        # Superset of active statuses for indexing model swaps
        return self.active_statuses() + [
            ConnectorCredentialPairStatus.PAUSED,
        ]

    def is_active(self) -> bool:
        return self in self.active_statuses()


class AccessType(str, PyEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    SYNC = "sync"


class EmbeddingPrecision(str, PyEnum):
    # matches vespa tensor type
    # only support float / bfloat16 for now, since there's not a
    # good reason to specify anything else
    BFLOAT16 = "bfloat16"
    FLOAT = "float"


class UserFileStatus(str, PyEnum):
    PROCESSING = "PROCESSING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    DELETING = "DELETING"


class ThemePreference(str, PyEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class SupportedLanguage(str, PyEnum):
    EN = "en"
    ES = "es"
    PT = "pt"
    FR = "fr"
    DE = "de"


class DefaultAppMode(str, PyEnum):
    AUTO = "AUTO"
    CHAT = "CHAT"
    SEARCH = "SEARCH"


class SwitchoverType(str, PyEnum):
    REINDEX = "reindex"
    ACTIVE_ONLY = "active_only"
    INSTANT = "instant"


class OpenSearchDocumentMigrationStatus(str, PyEnum):
    """Status for Vespa to OpenSearch migration per document."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    PERMANENTLY_FAILED = "permanently_failed"


class OpenSearchTenantMigrationStatus(str, PyEnum):
    """Status for tenant-level OpenSearch migration."""

    PENDING = "pending"
    COMPLETED = "completed"


# Onyx Build Mode Enums
class BuildSessionStatus(str, PyEnum):
    ACTIVE = "active"
    IDLE = "idle"


class SessionOrigin(str, PyEnum):
    """How a BuildSession was created.

    INTERACTIVE: session started by a user in the Craft UI.
    SCHEDULED:   session started by the scheduled-tasks executor (or any
                 future non-interactive caller). Sessions with this origin
                 are excluded from the Craft sidebar list.
    """

    INTERACTIVE = "INTERACTIVE"
    SCHEDULED = "SCHEDULED"


class SharingScope(str, PyEnum):
    PRIVATE = "private"
    PUBLIC_ORG = "public_org"


class ApprovalDecision(str, PyEnum):
    """Terminal decision on a gated action; `decision IS NULL` means pending."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ApprovalDecidedVia(str, PyEnum):
    # NULL on legacy rows and proxy-written EXPIRED claims.
    USER = "USER"
    PRE_APPROVAL = "PRE_APPROVAL"
    SESSION_GRANT = "SESSION_GRANT"


class ScheduledTaskStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class ScheduledTaskRunStatus(str, PyEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"

    def is_terminal(self) -> bool:
        """Terminal statuses produce no further state transitions in V1."""
        return self in (
            ScheduledTaskRunStatus.SUCCEEDED,
            ScheduledTaskRunStatus.FAILED,
            ScheduledTaskRunStatus.SKIPPED,
        )


class ScheduledTaskTriggerSource(str, PyEnum):
    SCHEDULED = "SCHEDULED"
    MANUAL_RUN_NOW = "MANUAL_RUN_NOW"


class ScheduledTaskErrorClass(str, PyEnum):
    """Closed set of values for ``ScheduledTaskRun.error_class``.

    Every code path that writes ``error_class`` must use a member of
    this enum — the column is intentionally a closed set so dashboards
    and triage queries can pivot on a known vocabulary. For unexpected
    runtime failures inside the agent drive, use ``AGENT_EXCEPTION``
    and put the actual exception class name + message in
    ``error_detail``.
    """

    TASK_MISSING = "task_missing"
    SANDBOX_WAKE_FAILED = "sandbox_wake_failed"
    EXECUTOR_ERROR = "executor_error"
    TIMEOUT = "timeout"
    STUCK = "stuck"
    AGENT_EXCEPTION = "agent_exception"


class ScheduledTaskSkipReason(str, PyEnum):
    """Well-known values for ``ScheduledTaskRun.skip_reason``."""

    PRIOR_IN_FLIGHT = "prior_in_flight"


class SandboxStatus(str, PyEnum):
    PROVISIONING = "provisioning"
    RUNNING = "running"
    SLEEPING = "sleeping"  # Pod terminated, snapshots saved to FileStore
    TERMINATED = "terminated"
    FAILED = "failed"

    def is_active(self) -> bool:
        """Check if sandbox is in an active state (running)."""
        return self == SandboxStatus.RUNNING

    def is_terminal(self) -> bool:
        """Check if sandbox is in a terminal state."""
        return self in (SandboxStatus.TERMINATED, SandboxStatus.FAILED)

    def is_sleeping(self) -> bool:
        """Check if sandbox is sleeping (pod terminated but can be restored)."""
        return self == SandboxStatus.SLEEPING


class ExternalAppType(str, PyEnum):
    """Discriminator for the External Apps OAuth dispatch layer.

    Each built-in value names a provider with its own configured
    authorize URL, token URL, scope, and response parser in
    `external_apps.providers`. `CUSTOM` is for admin-defined apps
    that don't go through any built-in OAuth flow (static-token
    integrations, internal services, etc.).
    """

    GOOGLE_CALENDAR = "GOOGLE_CALENDAR"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    GMAIL = "GMAIL"
    SLACK = "SLACK"
    LINEAR = "LINEAR"
    GITHUB = "GITHUB"
    HUBSPOT = "HUBSPOT"
    CUSTOM = "CUSTOM"

    @property
    def is_built_in(self) -> bool:
        """True for provider-backed built-ins (unique per type per tenant),
        False for ``CUSTOM`` (admin-defined, can repeat). Use this to guard
        paths that only make sense for a single, well-known app per type."""
        return self is not ExternalAppType.CUSTOM


class EndpointPolicy(str, PyEnum):
    """What the egress layer does with an outbound request once it has been
    matched to an action of a connected external app."""

    ALWAYS = "ALWAYS"  # auto-approve: the call proceeds without prompting
    ASK = "ASK"  # require approval: the user accepts or denies in-session
    DENY = "DENY"  # block the call outright


# Strictness ordering: higher = stricter. When one request matches several
# actions, the strictest policy governs (sort/`max` with this key); readers
# of a persisted `actions` list rely on `actions[0]` being the strictest.
POLICY_SEVERITY: dict[EndpointPolicy, int] = {
    EndpointPolicy.ALWAYS: 0,
    EndpointPolicy.ASK: 1,
    EndpointPolicy.DENY: 2,
}


class PatType(str, PyEnum):
    USER = "USER"
    CRAFT = "CRAFT"


class ArtifactType(str, PyEnum):
    WEB_APP = "web_app"
    PPTX = "pptx"
    DOCX = "docx"
    IMAGE = "image"
    MARKDOWN = "markdown"
    EXCEL = "excel"


class HierarchyNodeType(str, PyEnum):
    """Types of hierarchy nodes across different sources"""

    # Generic
    FOLDER = "folder"

    # Root-level type
    SOURCE = "source"  # Root node for a source (e.g., "Google Drive")

    # Placeholder created when a child is indexed before its parent exists in the DB.
    # Promoted to the real type when the parent page is later processed.
    STUB = "stub"

    # Google Drive
    SHARED_DRIVE = "shared_drive"
    MY_DRIVE = "my_drive"

    # Confluence
    SPACE = "space"
    PAGE = "page"  # Confluence pages can be both hierarchy nodes AND documents

    # Jira
    PROJECT = "project"

    # Notion
    DATABASE = "database"
    WORKSPACE = "workspace"

    # Sharepoint
    SITE = "site"
    DRIVE = "drive"  # Document library within a site

    # Slack
    CHANNEL = "channel"


class LLMModelFlowType(str, PyEnum):
    CHAT = "chat"
    VISION = "vision"
    CONTEXTUAL_RAG = "contextual_rag"
    REASONING = "reasoning"


class HookPoint(str, PyEnum):
    DOCUMENT_INGESTION = "document_ingestion"
    DOCUMENT_PUSH = "document_push"
    QUERY_PROCESSING = "query_processing"


class HookFailStrategy(str, PyEnum):
    HARD = "hard"  # exception propagates, pipeline aborts
    SOFT = "soft"  # log error, return original input, pipeline continues


class Permission(str, PyEnum):
    """
    Permission tokens for group-based authorization and PAT scoping.
    full_admin_panel_access is an override — if present, any permission
    check passes.

    The read:*/write:* "API-surface scopes" are coarser than the capability
    tokens: they name request surfaces (search, chat, admin-read) rather than
    admin capabilities. They are implied by basic / admin (so they're never
    granted directly to a group) and exist primarily to scope Personal Access
    Tokens.
    """

    # Basic (auto-granted to every new group)
    BASIC_ACCESS = "basic"

    # Read tokens — implied only, never granted directly
    READ_CONNECTORS = "read:connectors"
    READ_DOCUMENT_SETS = "read:document_sets"
    READ_AGENTS = "read:agents"
    READ_USERS = "read:users"

    # API-surface scopes — coarse, implied by basic/admin, used to scope PATs.
    READ_SEARCH = "read:search"
    READ_CHAT = "read:chat"
    WRITE_CHAT = "write:chat"
    READ_ADMIN = "read:admin"
    GENERATE_IMAGE = "generate:image"

    # Add / Manage pairs
    ADD_AGENTS = "add:agents"
    MANAGE_AGENTS = "manage:agents"
    MANAGE_DOCUMENT_SETS = "manage:document_sets"
    ADD_CONNECTORS = "add:connectors"
    MANAGE_CONNECTORS = "manage:connectors"
    MANAGE_LLMS = "manage:llms"

    # Toggle tokens
    READ_AGENT_ANALYTICS = "read:agent_analytics"
    MANAGE_ACTIONS = "manage:actions"
    READ_QUERY_HISTORY = "read:query_history"
    MANAGE_USER_GROUPS = "manage:user_groups"
    CREATE_USER_API_KEYS = "create:user_api_keys"
    CREATE_SERVICE_ACCOUNT_API_KEYS = "create:service_account_api_keys"
    CREATE_SLACK_DISCORD_BOTS = "create:slack_discord_bots"

    # Role scopes — a bundle token implying the surfaces a given machine
    # identity may use. PAT-only; never granted to a group/user.
    CRAFT_SANDBOX = "craft_sandbox"

    # Override — any permission check passes
    FULL_ADMIN_PANEL_ACCESS = "admin"

    # Permissions that are implied by other grants and must never be stored
    # directly in the permission_grant table.
    IMPLIED: ClassVar[frozenset[Permission]]


Permission.IMPLIED = frozenset(
    {
        Permission.READ_CONNECTORS,
        Permission.READ_DOCUMENT_SETS,
        Permission.READ_AGENTS,
        Permission.READ_USERS,
        Permission.READ_SEARCH,
        Permission.READ_CHAT,
        Permission.WRITE_CHAT,
        Permission.READ_ADMIN,
        Permission.GENERATE_IMAGE,
    }
)


class PersonaSharePermission(str, PyEnum):
    """Level granted by a persona share row (user or group), or to the whole
    org via `Persona.public_permission`."""

    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class SkillSharePermission(str, PyEnum):
    """Level granted by a skill share row (user or group), or to the whole org
    via `Skill.public_permission`."""

    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class SkillAccessLevel(str, PyEnum):
    """Computed access the requesting user holds on a skill."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class PersonaAccessLevel(str, PyEnum):
    """Computed access the requesting user holds on a persona.

    OWNER outranks share rows; admins are reported as EDITOR unless owner."""

    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class PersonaSharingStatus(str, PyEnum):
    """Derived share state computed from a persona's columns by the sharing
    helpers (no DB column of its own): group-owned or row-shared counts as
    SHARED even with an empty share list; PUBLIC wins over both."""

    PRIVATE = "PRIVATE"
    SHARED = "SHARED"
    PUBLIC = "PUBLIC"
