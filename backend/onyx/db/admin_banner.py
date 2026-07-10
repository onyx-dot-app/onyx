from datetime import datetime
from datetime import timezone

from pydantic import BaseModel

from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The banner's authored content is one global fact, stored as a single value in
# the per-tenant KV store. It reaches users as a per-user SYSTEM_ANNOUNCEMENT
# notification synthesized on read, so there is no separate display endpoint.
ADMIN_BANNER_KV_KEY = "admin_banner"


class AdminBanner(BaseModel):
    title: str
    content: str | None
    # Admin's choice to also show the announcement as a first-visit popup.
    show_as_popup: bool = False
    # ISO-8601 timestamp of the last publish/edit.
    updated_at: str


def get_admin_banner() -> AdminBanner | None:
    try:
        raw = get_kv_store().load(ADMIN_BANNER_KV_KEY)
    except KvKeyNotFoundError:
        return None
    return AdminBanner.model_validate(raw)


def set_admin_banner(
    title: str, content: str | None, show_as_popup: bool = False
) -> AdminBanner:
    banner = AdminBanner(
        title=title,
        content=content,
        show_as_popup=show_as_popup,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    get_kv_store().store(ADMIN_BANNER_KV_KEY, banner.model_dump())
    logger.info(
        "Admin banner set (title=%s chars, content=%s chars)",
        len(title),
        len(content) if content else 0,
    )
    return banner


def clear_admin_banner() -> None:
    try:
        get_kv_store().delete(ADMIN_BANNER_KV_KEY)
    except KvKeyNotFoundError:
        # Clearing an absent banner is a no-op.
        pass
