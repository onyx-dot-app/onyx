from abc import ABC, abstractmethod
from collections.abc import Sequence

from sqlalchemy.orm import Session

from onyx.db.models import Integration, IntegrationAction
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import IntegrationConfig, RequestMatch
from onyx.sandbox_proxy.resolvers.mcp_matching import IntegrationMatchTarget
from onyx.tools.interface import Tool


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
        target: IntegrationMatchTarget,
        request: ProxiedRequest,
        db_session: Session,
    ) -> RequestMatch | None:
        """The actions that a sandbox request calls. ``target`` holds the
        cached URL settings of the integration. None: the request is not for
        this integration. No actions: a protocol request that calls no
        action."""
        raise NotImplementedError
