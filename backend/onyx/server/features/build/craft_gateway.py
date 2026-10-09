from fastapi import Request

from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.build.utils import is_craft_enabled_for_user
from onyx.tracing.flows import LLMFlow


def is_craft_gateway_request(request: Request, user: User) -> bool:
    """Session/API-key auth carries no token scopes and must never match —
    ``require_permission`` alone can't express "a gateway-capable scope must
    be present"."""
    token_scopes: list[Permission] | None = getattr(  # ods: ignore[getattr]
        request.state, "token_scopes", None
    )
    token_grants_gateway = (
        token_scopes is not None
        and Permission.USE_LLM_GATEWAY.value
        in resolve_effective_permissions({s.value for s in token_scopes})
    )
    return token_grants_gateway and is_craft_enabled_for_user(user)


def gateway_request_flow(request: Request, user: User) -> LLMFlow | None:
    """A CRAFT_SANDBOX token must stay on the Craft policy, craft-enabled
    requirement included; only a directly granted USE_LLM_GATEWAY skips it.
    Future caller-declared sources should become additional LLMFlow return
    values here, not booleans."""
    token_scopes: list[Permission] | None = getattr(  # ods: ignore[getattr]
        request.state, "token_scopes", None
    )
    if token_scopes is None:
        return None
    raw_scopes = {s.value for s in token_scopes}
    if Permission.CRAFT_SANDBOX.value in raw_scopes:
        if is_craft_gateway_request(request, user):
            return LLMFlow.CRAFT_LLM_GENERATION
        return None
    if Permission.USE_LLM_GATEWAY.value in resolve_effective_permissions(raw_scopes):
        return LLMFlow.LLM_GATEWAY
    return None
