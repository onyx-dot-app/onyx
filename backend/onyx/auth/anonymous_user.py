from collections.abc import Mapping
from typing import Any, cast

from onyx.configs.constants import (
    ANONYMOUS_USER_EMAIL,
    ANONYMOUS_USER_INFO_ID,
    KV_ANONYMOUS_USER_PERSONALIZATION_KEY,
    KV_ANONYMOUS_USER_PREFERENCES_KEY,
)
from onyx.db.enums import AccountType
from onyx.db.models import UserPreferences as UserPreferencesModel
from onyx.key_value_store.store import KeyValueStore, KvKeyNotFoundError
from onyx.server.manage.models import UserInfo, UserPersonalization, UserPreferences


def set_anonymous_user_preferences(
    store: KeyValueStore, preferences: UserPreferences
) -> None:
    store.store(KV_ANONYMOUS_USER_PREFERENCES_KEY, preferences.model_dump())


def set_anonymous_user_personalization(
    store: KeyValueStore, personalization: UserPersonalization
) -> None:
    store.store(KV_ANONYMOUS_USER_PERSONALIZATION_KEY, personalization.model_dump())


def load_anonymous_user_preferences(
    store: KeyValueStore, defaults: UserPreferencesModel
) -> UserPreferences:
    """The stored anonymous preferences over the column defaults."""
    preferences = UserPreferences.from_model(defaults, pinned_assistants=[])
    try:
        preferences_data = cast(
            Mapping[str, Any], store.load(KV_ANONYMOUS_USER_PREFERENCES_KEY)
        )
        return UserPreferences.model_validate(
            {**preferences.model_dump(), **preferences_data}
        )
    except KvKeyNotFoundError:
        return preferences.model_copy(update={"auto_scroll": True})


def fetch_anonymous_user_info(
    store: KeyValueStore, defaults: UserPreferencesModel
) -> UserInfo:
    """Fetch a UserInfo object for anonymous users (used for API responses).
    `defaults` is `fetch_user_preferences` for the anonymous account."""
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
        account_type=AccountType.ANONYMOUS,
        preferences=load_anonymous_user_preferences(store, defaults),
        personalization=personalization,
        is_anonymous_user=True,
        password_configured=False,
    )
