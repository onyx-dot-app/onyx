from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.admin_banner import clear_admin_banner
from onyx.db.admin_banner import get_active_admin_banner
from onyx.db.admin_banner import set_admin_banner
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Notification
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

MAX_TITLE_LEN = 200
MAX_CONTENT_LEN = 2000


class AdminBannerResponse(BaseModel):
    title: str
    content: str | None
    created_at: str | None


class AdminBannerUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LEN)
    content: str | None = Field(default=None, max_length=MAX_CONTENT_LEN)


admin_router = APIRouter(prefix="/admin/banner")


def _to_response(banner: Notification) -> AdminBannerResponse:
    return AdminBannerResponse(
        title=banner.title,
        content=banner.description,
        created_at=banner.first_shown.isoformat() if banner.first_shown else None,
    )


@admin_router.get("")
def get_admin_banner(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AdminBannerResponse | None:
    banner = get_active_admin_banner(db_session)
    return _to_response(banner) if banner else None


@admin_router.put("")
def upsert_admin_banner(
    request: AdminBannerUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AdminBannerResponse:
    title = request.title.strip()
    if not title:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Title must include non-whitespace characters",
        )

    content: str | None
    if request.content is None:
        content = None
    else:
        stripped_content = request.content.strip()
        content = stripped_content or None

    banner = set_admin_banner(db_session, title=title, content=content)
    if banner is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "No eligible users to receive the banner",
        )
    return _to_response(banner)


@admin_router.delete("", status_code=204)
def delete_admin_banner(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    clear_admin_banner(db_session)
