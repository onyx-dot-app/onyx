"""Shapes shared by the connection logic, the OAuth flow and the MCP SDK
token storage. Kept free of heavy imports so each of them can use it."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from onyx.db.models import IntegrationConnection
from shared_configs.contextvars import get_current_tenant_id

# Reason texts that a user reads.
SIGN_IN_SETTINGS_CHANGED_REASON = "Your admin changed the sign-in settings"
SIGN_IN_REJECTED_REASON = "The service no longer accepts this sign-in. Reconnect."
SIGN_IN_EXPIRED_REASON = "The sign-in expired and cannot be renewed. Reconnect."


class ConnectionSecret(BaseModel):
    """The one secret shape of every connection, stored encrypted in
    ``integration_connection.secret``."""

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    # api_key values and other typed fields, keyed by placeholder name.
    fields: dict[str, str] = Field(default_factory=dict)


def read_connection_secret(connection: IntegrationConnection) -> ConnectionSecret:
    return ConnectionSecret.model_validate(
        connection.secret.get_value(apply_mask=False)
    )


class ConnectionProblemCode(str, Enum):
    NOT_SET_UP = "not_set_up"
    NOT_CONNECTED = "not_connected"
    NEEDS_RECONNECT = "needs_reconnect"


class ConnectionState(str, Enum):
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"
    NEEDS_RECONNECT = "needs_reconnect"
    NOT_SET_UP = "not_set_up"


def expiry_from_expires_in(
    expires_in: int | float | None, now: datetime.datetime
) -> datetime.datetime | None:
    if expires_in is None:
        return None
    return now + datetime.timedelta(seconds=float(expires_in))


def connection_refresh_lock_name(integration_id: int, user_id: UUID | None) -> str:
    """One lock per connection, shared by every refresh path."""
    owner = str(user_id) if user_id is not None else "organization"
    return (
        f"integration_connection_refresh:{get_current_tenant_id()}:"
        f"{integration_id}:{owner}"
    )
