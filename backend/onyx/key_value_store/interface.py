import abc
from typing import cast

from onyx.utils.special_types import JSON_ro


class KvKeyNotFoundError(Exception):
    pass


def unwrap_str(val: JSON_ro) -> str:
    """Unwrap a string stored as {"value": str} in the encrypted KV store.
    Also handles legacy plain-string values cached in Redis."""
    if isinstance(val, dict):
        try:
            return cast(str, val["value"])
        except KeyError:
            raise ValueError(
                f"Expected dict with 'value' key, got keys: {list(val.keys())}"
            )
    return cast(str, val)


class KeyValueStore:
    # In the Multi Tenant case, the tenant context is picked up automatically, it does not need to be passed in
    # It's read from the global thread level variable
    @abc.abstractmethod
    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def load(self, key: str, refresh_cache: bool = False) -> JSON_ro:
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError
