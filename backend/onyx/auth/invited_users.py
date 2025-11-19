from typing import cast

from onyx.configs.constants import KV_PENDING_USERS_KEY
from onyx.configs.constants import KV_USER_STORE_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.special_types import JSON_ro


def remove_user_from_invited_users(email: str) -> int:
    try:
        store = get_kv_store()
        user_emails = cast(list, store.load(KV_USER_STORE_KEY))
        remaining_users = [user for user in user_emails if user != email]
        store.store(KV_USER_STORE_KEY, cast(JSON_ro, remaining_users))
        return len(remaining_users)
    except KvKeyNotFoundError:
        return 0


def get_invited_users() -> list[str]:
    try:
        store = get_kv_store()
        return cast(list, store.load(KV_USER_STORE_KEY))
    except KvKeyNotFoundError:
        return list()


def write_invited_users(emails: list[str]) -> int:
    store = get_kv_store()
    store.store(KV_USER_STORE_KEY, cast(JSON_ro, emails))
    return len(emails)


def get_pending_users() -> list[str]:
    try:
        store = get_kv_store()
        return cast(list, store.load(KV_PENDING_USERS_KEY))
    except KvKeyNotFoundError:
        return list()


def write_pending_users(emails: list[str]) -> int:
    store = get_kv_store()
    store.store(KV_PENDING_USERS_KEY, cast(JSON_ro, emails))
    return len(emails)
