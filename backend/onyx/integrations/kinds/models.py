from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.tools.models import ToolApprovalScope


def _no_approval(_action_key: str) -> ToolApprovalScope | None:
    return None


class ChatToolContext(BaseModel):
    """What chat gives a kind to build the tools of one integration for one
    turn. The caller resolves the credentials and the policies."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID | None = None
    user_email: str | None = None
    chat_session_id: UUID | None = None
    message_id: int | None = None
    # Headers for each OpenAPI request: the rendered credential and the
    # caller's additional headers.
    custom_headers: dict[str, str] = {}
    # Sent as "Authorization: Bearer <token>" on each OpenAPI request.
    user_oauth_token: str | None = None
    # The MCP credentials of the acting user, or of the organization.
    mcp_resolved_credentials: ResolvedMCPCredentials | None = None
    mcp_headers: dict[str, str] | None = None
    # The approval scope of an action that asks, None for one that runs.
    approval_for: Callable[[str], ToolApprovalScope | None] = _no_approval
