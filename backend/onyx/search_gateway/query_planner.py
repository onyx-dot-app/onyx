from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Sequence

from onyx.search_gateway.models import SearchMode

DEFAULT_MEDIUM_MAX_QUERIES = 5
DEFAULT_DEEP_MAX_QUERIES = 8

_TECHNICAL_HINTS = (
    "api",
    "architecture",
    "benchmark",
    "compiler",
    "docs",
    "github",
    "npm",
    "package",
    "plugin",
    "project",
    "rust",
    "sdk",
    "typescript",
)

_MARKET_HINTS = (
    "btc",
    "crypto",
    "etf",
    "forex",
    "gold",
    "price",
    "stock",
    "走势",
    "价格",
    "今日",
    "今天",
    "行情",
    "黄金",
)


def build_effective_queries(
    queries: Sequence[str],
    *,
    mode: SearchMode,
    max_queries: int = DEFAULT_DEEP_MAX_QUERIES,
) -> list[str]:
    normalized_queries = _dedupe_preserving_order(
        _normalize_query(query) for query in queries
    )
    if mode is SearchMode.LITE:
        return normalized_queries
    if max_queries <= 0:
        return []

    expanded_queries: list[str] = []
    for query in normalized_queries:
        if mode is SearchMode.MEDIUM:
            expanded_queries.extend(_expand_medium_query(query))
        else:
            expanded_queries.extend(_expand_deep_query(query))

    query_limit = (
        min(max_queries, DEFAULT_MEDIUM_MAX_QUERIES)
        if mode is SearchMode.MEDIUM
        else max_queries
    )
    return _dedupe_preserving_order(expanded_queries)[:query_limit]


def _expand_medium_query(query: str) -> list[str]:
    if _looks_like_market_query(query):
        return [
            query,
            f"{query} latest market news today",
            f"{query} live price chart technical analysis",
            f"{query} forecast analyst commentary",
            f"{query} risks support resistance",
        ]

    if _looks_like_technical_query(query):
        return [
            query,
            f"{query} official documentation",
            f"{query} GitHub architecture core modules",
            f"{query} changelog release notes latest updates",
            f"{query} comparison benchmark limitations",
        ]

    return [
        query,
        f"{query} official source documentation",
        f"{query} latest analysis",
        f"{query} examples case study",
        f"{query} comparison limitations",
    ]


def _expand_deep_query(query: str) -> list[str]:
    if _looks_like_market_query(query):
        return [
            query,
            f"{query} latest market news today",
            f"{query} live price chart technical analysis",
            f"{query} macro drivers dollar yields central bank",
            f"{query} forecast analyst commentary",
            f"{query} risks support resistance",
        ]

    if _looks_like_technical_query(query):
        return [
            query,
            f"{query} official documentation",
            f"{query} GitHub architecture core modules",
            f"{query} changelog release notes latest updates",
            f"{query} issues discussions limitations",
            f"{query} comparison benchmark alternatives",
            f"{query} use cases limitations not suitable",
        ]

    return [
        query,
        f"{query} official source documentation",
        f"{query} latest analysis",
        f"{query} examples case study",
        f"{query} comparison alternatives",
        f"{query} limitations criticism",
    ]


def _looks_like_technical_query(query: str) -> bool:
    lowered = query.lower()
    return "/" in query or any(hint in lowered for hint in _TECHNICAL_HINTS)


def _looks_like_market_query(query: str) -> bool:
    lowered = query.lower()
    return any(hint in lowered for hint in _MARKET_HINTS)


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_query(query: str) -> str:
    return " ".join(query.split())
