from fastapi import Request

from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ReasoningEffort
from onyx.server.features.build.db.build_session import (
    fetch_accessible_build_llm_provider_by_id,
)
from onyx.server.features.build.utils import is_craft_enabled_for_user
from onyx.server.gateway.consumers import GatewayConsumer
from onyx.tracing.flows import LLMFlow


def _token_grants_gateway(request: Request, _user: User) -> bool:
    """Session/API-key auth carries no token scopes and must never match —
    ``require_permission`` alone can't express "a gateway-capable scope must
    be present"."""
    token_scopes: list[Permission] | None = getattr(request.state, "token_scopes", None)
    return (
        token_scopes is not None
        and Permission.USE_LLM_GATEWAY.value
        in resolve_effective_permissions({s.value for s in token_scopes})
    )


def _require_craft_enabled(_request: Request, user: User) -> None:
    if not is_craft_enabled_for_user(user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Onyx Craft is not available",
        )


CRAFT_GATEWAY_CONSUMER = GatewayConsumer(
    name="craft",
    flow=LLMFlow.CRAFT_LLM_GENERATION,
    matches=_token_grants_gateway,
    authorize=_require_craft_enabled,
    fetch_provider=fetch_accessible_build_llm_provider_by_id,
    default_reasoning_effort=ReasoningEffort.MEDIUM,
)
