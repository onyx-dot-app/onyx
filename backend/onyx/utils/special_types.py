from collections.abc import Mapping, Sequence
from typing import TypeAlias

JSON_ro: TypeAlias = (
    Mapping[str, "JSON_ro"] | Sequence["JSON_ro"] | str | int | float | bool | None
)
