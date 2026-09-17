import contextvars
from typing import NamedTuple

from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.enums import UsageCredentialType

# Context variable for the current tenant id
CURRENT_TENANT_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar(
        "current_tenant_id", default=None if MULTI_TENANT else POSTGRES_DEFAULT_SCHEMA
    )
)

# Workspace a session must be issued against, set only by a caller that already
# decided it. Not CURRENT_TENANT_ID_CONTEXTVAR: that is whatever cookie the
# request carried, which can name a workspace this user does not belong to.
SESSION_TENANT_OVERRIDE_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("session_tenant_override", default=None)
)

# set by every route in the API server
INDEXING_REQUEST_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("indexing_request_id", default=None)
)

# set by every route in the API server
ONYX_REQUEST_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "onyx_request_id", default=None
)

# Used to store cc pair id and index attempt id in multithreaded environments
INDEX_ATTEMPT_INFO_CONTEXTVAR: contextvars.ContextVar[tuple[int, int] | None] = (
    contextvars.ContextVar("index_attempt_info", default=None)
)

# Set by endpoint context middleware — used for per-endpoint DB pool attribution
CURRENT_ENDPOINT_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("current_endpoint", default=None)
)

# Per-request user id for usage attribution; None in workers.
CURRENT_USER_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_id", default=None
)

# IncognitoRecordMode value of the streaming turn's session, None outside
# incognito. A plain string keeps this layer free of onyx imports.
CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("current_incognito_record_mode", default=None)
)

# Session id of a content-free turn, and only of a content-free turn: a blob
# saved while this is set is conversation-derived and must die with the
# session, so the file store stamps it on the record at creation.
CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("current_content_free_session_id", default=None)
)


class UsageCredentialIdentity(NamedTuple):
    credential_type: UsageCredentialType
    credential_id: str | None = None
    credential_name: str | None = None
    credential_display: str | None = None


CURRENT_USAGE_CREDENTIAL_CONTEXTVAR: contextvars.ContextVar[
    UsageCredentialIdentity | None
] = contextvars.ContextVar("current_usage_credential", default=None)


def get_current_tenant_id() -> str:
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    if tenant_id is None:
        import traceback

        if not MULTI_TENANT:
            return POSTGRES_DEFAULT_SCHEMA

        stack_trace = traceback.format_stack()
        error_message = (
            "Tenant ID is not set. This should never happen.\nStack trace:\n"
            + "".join(stack_trace)
        )
        raise RuntimeError(error_message)
    return tenant_id


def get_current_user_id() -> str | None:
    """Requesting user's id, or None outside a per-request context."""
    return CURRENT_USER_ID_CONTEXTVAR.get()


def get_current_incognito_record_mode() -> str | None:
    """The incognito record-mode value of the current turn, None outside one."""
    return CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.get()


def get_current_usage_credential() -> UsageCredentialIdentity | None:
    return CURRENT_USAGE_CREDENTIAL_CONTEXTVAR.get()
