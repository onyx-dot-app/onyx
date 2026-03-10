"""SCIM filter expression parser (RFC 7644 §3.4.2.2).

Identity providers (Okta, Azure AD, OneLogin, etc.) use filters to look up
resources before deciding whether to create or update them. For example, when
an admin assigns a user to the Onyx app, the IdP first checks whether that
user already exists::

    GET /scim/v2/Users?filter=userName eq "john@example.com"

If zero results come back the IdP creates the user (``POST``); if a match is
found it links to the existing record and uses ``PUT``/``PATCH`` going forward.
The same pattern applies to groups (``displayName eq "Engineering"``).

This module parses the subset of the SCIM filter grammar that identity
providers actually send in practice:

    attribute SP operator SP value

Supported operators: ``eq``, ``co`` (contains), ``sw`` (starts with).
Compound filters (``and`` / ``or``) are not supported; if an IdP sends one
the parser returns ``None`` and the caller falls back to an unfiltered list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ScimFilterOperator(str, Enum):
    """Supported SCIM filter operators."""

    EQUAL = "eq"
    CONTAINS = "co"
    STARTS_WITH = "sw"


@dataclass(frozen=True, slots=True)
class ScimFilter:
    """Parsed SCIM filter expression."""

    attribute: str
    operator: ScimFilterOperator
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
        operator, or ``None`` if the input is empty / missing.

    Raises:
        ValueError: If the filter string is present but malformed or uses
            an unsupported operator.
    """
    if not filter_string or not filter_string.strip():
        return None

    match = _FILTER_RE.match(filter_string.strip())
    if not match:
        raise ValueError(f"Unsupported or malformed SCIM filter: {filter_string}")

    return _build_filter(match, filter_string)


def _build_filter(match: re.Match[str], raw: str) -> ScimFilter:
    """Extract fields from a regex match and construct a ScimFilter."""
    attribute = match.group(1)
    op_str = match.group(2).lower()
    # Value is in group 3 (double-quoted) or group 4 (single-quoted)
    value = match.group(3) if match.group(3) is not None else match.group(4)

    if value is None:
        raise ValueError(f"Unsupported or malformed SCIM filter: {raw}")

    operator = ScimFilterOperator(op_str)

    return ScimFilter(attribute=attribute, operator=operator, value=value)
