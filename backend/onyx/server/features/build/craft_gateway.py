from fastapi import Request

from onyx.auth.permissions import resolve_effective_permissions
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.build.utils import is_craft_enabled_for_user


def is_craft_gateway_request(request: Request, user: User) -> bool:
    """Session/API-key auth carries no token scopes and must never match —
    ``require_permission`` alone can't express "a gateway-capable scope must
    be present"."""
    token_scopes: list[Permission] | None = getattr(request.state, "token_scopes", None)
    token_grants_gateway = (
        token_scopes is not None
        and Permission.USE_LLM_GATEWAY.value
        in resolve_effective_permissions({s.value for s in token_scopes})
    )
    return token_grants_gateway and is_craft_enabled_for_user(user)
