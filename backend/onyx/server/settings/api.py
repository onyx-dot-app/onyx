from typing import cast

from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.configs.constants import KV_REINDEX_KEY
from onyx.db.models import User
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.build.utils import is_onyx_craft_enabled
from onyx.server.settings.models import Notification
from onyx.server.settings.models import Settings
from onyx.server.settings.models import UserSettings
from onyx.server.settings.store import load_settings
from onyx.server.settings.store import store_settings
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/settings")
basic_router = APIRouter(prefix="/settings")


@admin_router.put("")
def admin_put_settings(
    settings: Settings, _: User = Depends(current_admin_user)
) -> None:
    store_settings(settings)


def apply_license_status_to_settings(settings: Settings) -> Settings:
    """MIT version: no-op, returns settings unchanged."""
    return settings


@basic_router.get("")
def fetch_settings(
    _: User = Depends(current_user),
) -> UserSettings:
    general_settings = load_settings()

    try:
        kv_store = get_kv_store()
        needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
    except KvKeyNotFoundError:
        needs_reindexing = False

    apply_fn = fetch_versioned_implementation_with_fallback(
        "onyx.server.settings.api",
        "apply_license_status_to_settings",
        apply_license_status_to_settings,
    )
    general_settings = apply_fn(general_settings)

    # Check if Onyx Craft is enabled for this user (used for server-side redirects)
    onyx_craft_enabled_for_user = is_onyx_craft_enabled(user) if user else False

    return UserSettings(
        **general_settings.model_dump(),
        notifications=[],
        needs_reindexing=needs_reindexing,
        onyx_craft_enabled=onyx_craft_enabled_for_user,
    )
