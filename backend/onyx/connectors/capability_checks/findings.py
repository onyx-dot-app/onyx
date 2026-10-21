"""Helpers for checks that return findings (``models.py:CheckFinding``)."""

from collections.abc import Callable, Iterable
from itertools import islice
from typing import TypeVar

from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    MAX_FINDING_TEXT_LENGTH,
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
    the check keeps inside its timeout. Labels and details longer than
    ``MAX_FINDING_TEXT_LENGTH`` are shortened; an item whose value is longer is
    left out, since a shortened value would not match the config."""
    taken: list[_T] = list(islice(items, MAX_FINDING_OPTIONS + 1))
    options: list[FindingOption] = []
    for item in taken[:MAX_FINDING_OPTIONS]:
        option_value: str = value(item)
        if len(option_value) > MAX_FINDING_TEXT_LENGTH:
            continue
        option_detail: str | None = detail(item) if detail is not None else None
        options.append(
            FindingOption(
                value=option_value,
                label=_shorten(label(item)),
                detail=_shorten(option_detail) if option_detail is not None else None,
            )
        )
    return OptionsFinding(
        key=key,
        field_name=field_name,
        options=options,
        truncated=len(taken) > MAX_FINDING_OPTIONS,
    )


def _shorten(text: str) -> str:
    if len(text) <= MAX_FINDING_TEXT_LENGTH:
        return text
    return text[: MAX_FINDING_TEXT_LENGTH - 1] + "\u2026"


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
