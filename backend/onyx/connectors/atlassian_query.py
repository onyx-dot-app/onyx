"""Shape rules for the CQL and JQL queries that Confluence and Jira configs
hold. The connectors add their own clauses around these queries."""

import re

_LAST_MODIFIED_PATTERN = re.compile(r"\blastmodified\b", re.IGNORECASE)
_ORDER_BY_PATTERN = re.compile(r"\border\s+by\b", re.IGNORECASE)
# A quoted CQL or JQL value; a backslash escapes the next character.
_QUOTED_PATTERN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")


def _unquoted(query: str) -> str:
    return _QUOTED_PATTERN.sub('""', query)


def has_last_modified_filter(query: str) -> bool:
    """True when ``lastModified`` occurs outside a quoted value."""
    return bool(_LAST_MODIFIED_PATTERN.search(_unquoted(query)))


def has_order_by(query: str) -> bool:
    """True when ``ORDER BY`` occurs outside a quoted value."""
    return bool(_ORDER_BY_PATTERN.search(_unquoted(query)))
