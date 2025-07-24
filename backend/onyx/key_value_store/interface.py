import abc

from onyx.utils.special_types import JSON_ro


class KvKeyNotFoundError(Exception):
    pass


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
