from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.db.models import Integration, IntegrationAction
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.models import (
    IntegrationActionSpec,
    IntegrationConfig,
    MatchedIntegrationAction,
)
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.tools.interface import Tool
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


class IntegrationKindHandler(ABC):
    """The code of one integration kind. A kind reads its kind table only for
    the settings of the kind, never for the name, owner, access, sign-in or
    approval columns."""

    @abstractmethod
    def load_config(
        self, integration: Integration, db_session: Session
    ) -> IntegrationConfig:
        raise NotImplementedError

    @abstractmethod
    def discover_actions(
        self, integration: Integration, db_session: Session
    ) -> list[IntegrationActionSpec]:
        """Makes no network call."""
        raise NotImplementedError

    @abstractmethod
    def build_chat_tools(
        self,
        integration: Integration,
        actions: Sequence[IntegrationAction],
        ctx: ChatToolContext,
        db_session: Session,
    ) -> list[Tool]:
        raise NotImplementedError

    @abstractmethod
    def match_request(
        self,
        integration: Integration,
        request: ProxiedRequest,
        db_session: Session,
    ) -> list[MatchedIntegrationAction] | None:
        """The actions that a sandbox request calls. None: the request is not
        for this integration. An empty list: a protocol request that calls no
        action."""
        raise NotImplementedError
