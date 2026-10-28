from fastapi import Request

from onyx.auth.pat import get_token_permission_cap
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.build.utils import is_craft_enabled_for_user
from onyx.tracing.flows import LLMFlow
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


def is_craft_gateway_request(request: Request, user: User) -> bool:
    """Session/API-key auth carries no token scopes and must never match —
    ``require_permission`` alone can't express "a gateway-capable scope must
    be present"."""
    cap = get_token_permission_cap(request)
    token_grants_gateway = cap is not None and Permission.USE_LLM_GATEWAY in cap
    return token_grants_gateway and is_craft_enabled_for_user(user)


def gateway_request_flow(request: Request, user: User) -> LLMFlow | None:
    """Apply Craft policy to internal tokens and the stored cap to user tokens."""
    state = request.scope.get("state", {})
    token_scopes: list[Permission] | None = state.get("token_scopes")
    credential: UsageCredentialIdentity | None = state.get("usage_credential")
    if credential is None:
        return None
    if credential.credential_type is UsageCredentialType.CRAFT_PAT:
        if (
            token_scopes is not None
            and Permission.CRAFT_SANDBOX in token_scopes
            and is_craft_gateway_request(request, user)
        ):
            return LLMFlow.CRAFT_LLM_GENERATION
        return None
    cap = get_token_permission_cap(request)
    if (
        credential.credential_type is UsageCredentialType.PAT
        and cap is not None
        and Permission.USE_LLM_GATEWAY in cap
    ):
        return LLMFlow.LLM_GATEWAY
    return None
