"""SCIM filter expression parser (RFC 7644 §3.4.2.2).

SCIM clients (Okta, Azure AD) pass filter query parameters on list endpoints
to narrow results — e.g. ``GET /scim/v2/Users?filter=userName eq "j@x.com"``.

This module parses the subset of the SCIM filter grammar that identity
providers actually use in practice:

    attribute SP operator SP value

Supported operators: ``eq``, ``co`` (contains), ``sw`` (starts with).
Compound filters (``and`` / ``or``) are not supported; if an IdP sends one
the parser returns ``None`` and the caller falls back to an unfiltered list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ScimFilterOp(str, Enum):
    """Supported SCIM filter operators."""

    EQ = "eq"
    CO = "co"
    SW = "sw"


@dataclass(frozen=True, slots=True)
class ScimFilter:
    """Parsed SCIM filter expression."""

    attribute: str
    operator: ScimFilterOp
    value: str


# Matches: attribute operator "value" (with or without quotes around value)
# Groups: (attribute) (operator) ("quoted value" | unquoted_value)
_FILTER_RE = re.compile(
    r"^(\S+)\s+(eq|co|sw)\s+"  # attribute + operator
    r'(?:"([^"]*)"'  # quoted value
    r"|'([^']*)')"  # or single-quoted value
    r"$",
    re.IGNORECASE,
)


def parse_scim_filter(filter_string: str | None) -> ScimFilter | None:
    """Parse a simple SCIM filter expression.

    Args:
        filter_string: Raw filter query parameter value, e.g.
            ``'userName eq "john@example.com"'``

    Returns:
        A ``ScimFilter`` if the expression is valid and uses a supported
        operator, otherwise ``None``.
    """
    if not filter_string or not filter_string.strip():
        return None

    match = _FILTER_RE.match(filter_string.strip())
    if not match:
        return None

    attribute = match.group(1)
    op_str = match.group(2).lower()
    # Value is in group 3 (double-quoted) or group 4 (single-quoted)
    value = match.group(3) if match.group(3) is not None else match.group(4)

    if value is None:
        return None

    try:
        operator = ScimFilterOp(op_str)
    except ValueError:
        return None

    return ScimFilter(attribute=attribute, operator=operator, value=value)
