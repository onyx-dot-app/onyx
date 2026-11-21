"""Per-field edit policies for connector config models.

A config field declares its policy as ``Annotated`` metadata, e.g.
``channels: Annotated[list[str] | None, FieldPolicy(FieldClass.SCOPE,
scope=ScopeInclude(empty_means_all=True))] = None``. The policy tells a config
edit what work it needs (re-index, prune, scoped backfill). This module must
stay light to import: every connector config module imports it.

Keep FieldPolicy as plain metadata. Pydantic uses a model in
``Annotated`` metadata to build the field schema.
"""

import dataclasses
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.fields import FieldInfo


class FieldClass(str, Enum):
    # Part of document ids: a change needs a full re-index and a prune.
    IDENTITY = "identity"
    # Selects which documents are fetched.
    SCOPE = "scope"
    # Changes how fetched documents are processed: a change needs a full re-index.
    BEHAVIOR = "behavior"
    # Has no effect on indexed data.
    COSMETIC = "cosmetic"


class ScopeDirection(str, Enum):
    NONE = "none"
    WIDEN = "widen"
    NARROW = "narrow"
    BOTH = "both"
    UNKNOWN = "unknown"


class ScopeInclude(BaseModel):
    """Items to fetch. Values are a list, None, or a comma-separated string.

    With ``empty_means_all``, an empty value fetches everything. With
    ``empty_list_means_none`` too, only None (or a blank string) fetches
    everything, and an empty list fetches nothing. Set ``split_on_commas`` to
    False for a string that holds one item which can contain commas (e.g. a
    folder path).
    """

    model_config = ConfigDict(strict=True, frozen=True)

    empty_means_all: bool
    empty_list_means_none: bool = False
    split_on_commas: bool = True

    def model_post_init(self, __context: Any) -> None:
        if self.empty_list_means_none and not self.empty_means_all:
            raise ValueError("empty_list_means_none needs empty_means_all")


class ScopeExclude(BaseModel):
    """Items to skip. Values are a list, None, or a comma-separated string.

    ``split_on_commas`` works as on ``ScopeInclude``.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    split_on_commas: bool = True


class ScopeToggle(BaseModel):
    """A bool that fetches more documents when it is ``widens_when``."""

    model_config = ConfigDict(strict=True, frozen=True)

    widens_when: bool


class ScopeOrdered(BaseModel):
    """A limit or a date floor. A larger value fetches more documents when
    ``widens_when_larger``, fewer otherwise. ``unbounded`` lists the values
    that mean no limit (the widest scope). ``none_means`` is the value the
    connector uses when the field is None."""

    model_config = ConfigDict(strict=True, frozen=True)

    widens_when_larger: bool
    unbounded: tuple[Any, ...] = ()
    none_means: Any = None


class ScopeOpaque(BaseModel):
    """A scope field whose change direction cannot be derived from its values."""

    model_config = ConfigDict(strict=True, frozen=True)


ScopeDescriptor = ScopeInclude | ScopeExclude | ScopeToggle | ScopeOrdered | ScopeOpaque


@dataclasses.dataclass(frozen=True)  # noqa: TID251 - FieldPolicy is Annotated metadata. Pydantic model metadata replaces the field schema.
class FieldPolicy:
    """``depends_on`` names mode fields: if one of them changes, a change to
    this field has an unknown direction."""

    field_class: FieldClass
    scope: ScopeDescriptor | None = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.field_class != FieldClass.SCOPE and (self.scope or self.depends_on):
            raise ValueError(
                f"Only SCOPE fields take a scope descriptor or depends_on, not {self.field_class.value}"
            )


def get_field_policy(field_info: FieldInfo) -> FieldPolicy | None:
    return next(
        (item for item in field_info.metadata if isinstance(item, FieldPolicy)),
        None,
    )
