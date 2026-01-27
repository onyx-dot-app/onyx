from collections.abc import Mapping
from typing import Any
from typing import cast

from onyx.auth.schemas import UserRole
from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.configs.constants import ANONYMOUS_USER_INFO_ID
from onyx.configs.constants import KV_ANONYMOUS_USER_PERSONALIZATION_KEY
from onyx.configs.constants import KV_ANONYMOUS_USER_PREFERENCES_KEY
from onyx.key_value_store.store import KeyValueStore
from onyx.key_value_store.store import KvKeyNotFoundError
from onyx.server.manage.models import UserInfo
from onyx.server.manage.models import UserPersonalization
from onyx.server.manage.models import UserPreferences


def set_anonymous_user_preferences(
    store: KeyValueStore, preferences: UserPreferences
) -> None:
    store.store(KV_ANONYMOUS_USER_PREFERENCES_KEY, preferences.model_dump())


def set_anonymous_user_personalization(
    store: KeyValueStore, personalization: UserPersonalization
) -> None:
    store.store(KV_ANONYMOUS_USER_PERSONALIZATION_KEY, personalization.model_dump())


def load_anonymous_user_preferences(store: KeyValueStore) -> UserPreferences:
    try:
        preferences_data = cast(
            Mapping[str, Any], store.load(KV_ANONYMOUS_USER_PREFERENCES_KEY)
        )
        return UserPreferences(**preferences_data)
    except KvKeyNotFoundError:
        return UserPreferences(
            chosen_assistants=None, default_model=None, auto_scroll=True
        )


def fetch_anonymous_user_info(store: KeyValueStore) -> UserInfo:
    """Fetch a UserInfo object for anonymous users (used for API responses)."""
    personalization = UserPersonalization()
    try:
        personalization_data = cast(
            Mapping[str, Any], store.load(KV_ANONYMOUS_USER_PERSONALIZATION_KEY)
        )
        personalization = UserPersonalization(**personalization_data)
    except KvKeyNotFoundError:
        pass

    return UserInfo(
        id=ANONYMOUS_USER_INFO_ID,
        email=ANONYMOUS_USER_EMAIL,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.LIMITED,
        preferences=load_anonymous_user_preferences(store),
        personalization=personalization,
        is_anonymous_user=True,
        password_configured=False,
    )
