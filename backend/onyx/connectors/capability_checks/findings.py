"""Helpers for checks that return findings (``models.py:CheckFinding``)."""

from collections.abc import Callable, Iterable
from itertools import islice
from typing import TypeVar

from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CheckFindingKey,
    CountFinding,
    FindingOption,
    OptionsFinding,
)

_T = TypeVar("_T")


def bounded_options(
    items: Iterable[_T],
    *,
    key: CheckFindingKey,
    field_name: str | None,
    value: Callable[[_T], str],
    label: Callable[[_T], str],
    detail: Callable[[_T], str | None] | None = None,
) -> OptionsFinding:
    """Options from a listing, read lazily up to ``MAX_FINDING_OPTIONS``. Pass a
    generator over the source's pages, so a long listing stops at the cap and
    the check keeps inside its timeout."""
    taken: list[_T] = list(islice(items, MAX_FINDING_OPTIONS + 1))
    return OptionsFinding(
        key=key,
        field_name=field_name,
        options=[
            FindingOption(
                value=value(item),
                label=label(item),
                detail=detail(item) if detail is not None else None,
            )
            for item in taken[:MAX_FINDING_OPTIONS]
        ],
        truncated=len(taken) > MAX_FINDING_OPTIONS,
    )


def bounded_count(
    items: Iterable[object],
    *,
    key: CheckFindingKey,
    cap: int,
    field_name: str | None = None,
) -> CountFinding:
    """The number of items in a listing, read lazily up to ``cap``."""
    counted: int = sum(1 for _ in islice(items, cap + 1))
    return CountFinding(
        key=key,
        field_name=field_name,
        count=min(counted, cap),
        at_least=counted > cap,
    )
