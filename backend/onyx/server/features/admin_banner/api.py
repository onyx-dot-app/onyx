from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field

from onyx.auth.permissions import require_permission
from onyx.db.admin_banner import AdminBanner
from onyx.db.admin_banner import clear_admin_banner
from onyx.db.admin_banner import get_admin_banner
from onyx.db.admin_banner import set_admin_banner
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

MAX_TITLE_LEN = 200
MAX_CONTENT_LEN = 2000


class AdminBannerUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LEN)
    content: str | None = Field(default=None, max_length=MAX_CONTENT_LEN)


# Admin-only configuration of the single site-wide banner.
admin_router = APIRouter(prefix="/admin/banner")
# Read-only display endpoint every signed-in user reads to render the banner.
banner_router = APIRouter(prefix="/banner")


@admin_router.get("")
def get_admin_banner_config(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> AdminBanner | None:
    return get_admin_banner()


@admin_router.put("")
def upsert_admin_banner(
    request: AdminBannerUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> AdminBanner:
    title = request.title.strip()
    if not title:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Title must include non-whitespace characters",
        )
    content = (request.content or "").strip() or None
    return set_admin_banner(title=title, content=content)


@admin_router.delete("", status_code=204)
def delete_admin_banner(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    clear_admin_banner()


@banner_router.get("")
def get_active_banner(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> AdminBanner | None:
    return get_admin_banner()
