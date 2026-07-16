from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import NotificationType
from onyx.db.admin_banner import AdminBanner
from onyx.db.admin_banner import clear_admin_banner
from onyx.db.admin_banner import get_admin_banner
from onyx.db.admin_banner import set_admin_banner
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.notification import delete_notifications_by_type
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

MAX_TITLE_LEN = 100
MAX_CONTENT_LEN = 1000


class AdminBannerUpdateRequest(BaseModel):
    title: str = Field(..., max_length=MAX_TITLE_LEN)
    content: str | None = Field(default=None, max_length=MAX_CONTENT_LEN)
    show_as_popup: bool = False


# Admin-only configuration of the single site-wide banner. Users receive it
# through the notification feed (synthesized per-user on read), not a dedicated
# display endpoint, so publish/clear here wipes all SYSTEM_ANNOUNCEMENT rows.
admin_router = APIRouter(prefix="/admin/banner")


@admin_router.get("")
def get_admin_banner_config(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> AdminBanner | None:
    return get_admin_banner()


@admin_router.put("")
def upsert_admin_banner(
    request: AdminBannerUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AdminBanner:
    title = request.title.strip()
    if not title:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Title must include non-whitespace characters",
        )
    content = (request.content or "").strip() or None
    banner = set_admin_banner(
        title=title, content=content, show_as_popup=request.show_as_popup
    )
    # Clear existing rows so every user re-materializes the edited banner.
    delete_notifications_by_type(NotificationType.SYSTEM_ANNOUNCEMENT, db_session)
    return banner


@admin_router.delete("", status_code=204)
def delete_admin_banner(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    clear_admin_banner()
    delete_notifications_by_type(NotificationType.SYSTEM_ANNOUNCEMENT, db_session)
