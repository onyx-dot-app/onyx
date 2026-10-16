from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.api_token import get_api_token_usages, list_api_tokens, rotate_api_token
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import ApiToken, User
from onyx.server.manage.api_token.models import (
    ApiTokenRotateRequest,
    ApiTokenUsage,
    ApiTokenView,
)
from onyx.utils.encryption import mask_string

admin_router = APIRouter(prefix="/admin/api-tokens")


def _to_views(db_session: Session, tokens: list[ApiToken]) -> list[ApiTokenView]:
    usages = get_api_token_usages(db_session, [token.id for token in tokens])
    return [
        ApiTokenView(
            id=token.id,
            platform=token.platform,
            masked_value=mask_string(token.value.get_value(apply_mask=False)),
            usages=[
                ApiTokenUsage(kind=kind, name=name) for kind, name in usages[token.id]
            ],
        )
        for token in tokens
    ]


@admin_router.get("")
def list_tokens(
    platform: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ApiTokenView]:
    """Saved keys for one platform, masked, with the places that use them."""
    return _to_views(db_session, list_api_tokens(db_session, platform))


@admin_router.patch("/{token_id}")
def rotate_token(
    token_id: int,
    request: ApiTokenRotateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApiTokenView:
    """Replace a key's value. Every feature that uses it gets the new value."""
    token = rotate_api_token(db_session, token_id, request.value)
    db_session.commit()
    return _to_views(db_session, [token])[0]
