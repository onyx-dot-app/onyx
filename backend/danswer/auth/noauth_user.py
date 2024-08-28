from collections.abc import Mapping
from typing import Any
from typing import cast

from danswer.auth.schemas import UserRole
from danswer.configs.constants import KV_NO_AUTH_USER_PREFERENCES_KEY
from danswer.dynamic_configs.store import ConfigNotFoundError
from danswer.dynamic_configs.store import DynamicConfigStore
from danswer.server.manage.models import UserInfo
from danswer.server.manage.models import UserPreferences


def set_no_auth_user_preferences(
    store: DynamicConfigStore, preferences: UserPreferences
) -> None:
    store.store(KV_NO_AUTH_USER_PREFERENCES_KEY, preferences.dict())


def load_no_auth_user_preferences(store: DynamicConfigStore) -> UserPreferences:
    try:
        preferences_data = cast(
            Mapping[str, Any], store.load(KV_NO_AUTH_USER_PREFERENCES_KEY)
        )
        return UserPreferences(**preferences_data)
    except ConfigNotFoundError:
        return UserPreferences(chosen_assistants=None, default_model=None)


def fetch_no_auth_user(store: DynamicConfigStore) -> UserInfo:
    return UserInfo(
        id="__no_auth_user__",
        email="anonymous@danswer.ai",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.ADMIN,
        preferences=load_no_auth_user_preferences(store),
    )
