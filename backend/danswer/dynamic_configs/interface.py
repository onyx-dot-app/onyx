import abc
from collections.abc import Mapping
from collections.abc import Sequence
from typing import TypeAlias


JSON_ro: TypeAlias = (
    Mapping[str, "JSON_ro"] | Sequence["JSON_ro"] | str | int | float | bool | None
)


class ConfigNotFoundError(Exception):
    pass


class DynamicConfigStore:
    @abc.abstractmethod
    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def load(self, key: str) -> JSON_ro:
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError
