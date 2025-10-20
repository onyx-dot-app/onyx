from enum import Enum as PyEnum


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


class IndexingMode(str, PyEnum):
    UPDATE = "update"
    REINDEX = "reindex"


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


class MCPTransport(str, PyEnum):
    """MCP transport types"""

    STDIO = "STDIO"  # TODO: currently unsupported, need to add a user guide for setup
    SSE = "SSE"  # Server-Sent Events (deprecated but still used)
    STREAMABLE_HTTP = "STREAMABLE_HTTP"  # Modern HTTP streaming


class MCPAuthenticationPerformer(str, PyEnum):
    ADMIN = "ADMIN"
    PER_USER = "PER_USER"


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
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    DELETING = "DELETING"
