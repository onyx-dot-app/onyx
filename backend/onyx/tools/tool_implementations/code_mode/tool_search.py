"""tool_search(): how programs find the deferred functions, which the
`execute_code` description does not list."""

import math
import re
from collections import Counter
from collections.abc import Sequence

from onyx.tools.tool_implementations.code_mode.models import SearchableFunction

TOOL_SEARCH_FUNCTION = "tool_search"
TOOL_MATCH_TYPE = "ToolMatch"
# Names the tool search adds to a program's globals.
TOOL_SEARCH_NAMES: frozenset[str] = frozenset({TOOL_SEARCH_FUNCTION, TOOL_MATCH_TYPE})
DEFAULT_TOOL_SEARCH_LIMIT = 8
MAX_TOOL_SEARCH_LIMIT = 20

TOOL_SEARCH_STUBS = f'''class {TOOL_MATCH_TYPE}(TypedDict):
    name: str
    description: str
    stub: str


async def {TOOL_SEARCH_FUNCTION}(query: str, limit: int = {DEFAULT_TOOL_SEARCH_LIMIT}) -> list[{TOOL_MATCH_TYPE}]:
    """Find functions that this description does not list, best match first.

    Each match has the function name, its description, and its full stub with
    the argument and result types. At most `limit` matches, up to {MAX_TOOL_SEARCH_LIMIT}.
    """
    ...'''

# Runs of letters and digits in any script; `_` and other symbols split words.
_TOKEN = re.compile(r"[^\W_]+")
# BM25 parameters: term frequency saturation and document length normalization.
_K1 = 1.2
_B = 0.75


def _tokens(text: str) -> list[str]:
    # Splits snake_case, kebab-case and camelCase names into words.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return _TOKEN.findall(spaced.lower())


class ToolIndex:
    """BM25 ranking over the deferred functions of one program."""

    def __init__(self, functions: Sequence[SearchableFunction]) -> None:
        self._functions = list(functions)
        self._terms = [Counter(_tokens(function.text)) for function in functions]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        frequencies = Counter(term for terms in self._terms for term in terms)
        count = len(self._functions)
        self._idf = {
            term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in frequencies.items()
        }

    def search(self, query: str, limit: int) -> list[SearchableFunction]:
        query_terms = set(_tokens(query))
        scored: list[tuple[float, int]] = []
        for index, terms in enumerate(self._terms):
            length_norm = (
                1 - _B + _B * self._lengths[index] / (self._average_length or 1.0)
            )
            score = sum(
                self._idf[term]
                * terms[term]
                * (_K1 + 1)
                / (terms[term] + _K1 * length_norm)
                for term in query_terms
                if term in terms
            )
            if score > 0:
                scored.append((score, index))
        # Ties keep name order.
        scored.sort(key=lambda item: (-item[0], self._functions[item[1]].name))
        return [self._functions[index] for _, index in scored[:limit]]

    def tool_search(
        self, query: object, limit: object = DEFAULT_TOOL_SEARCH_LIMIT
    ) -> list[dict[str, str]]:
        """Answer a program's tool_search() call; raises TypeError or ValueError
        for invalid arguments, as Python would."""
        if not isinstance(query, str):
            raise TypeError(f"query must be str, not {type(query).__name__}")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise TypeError(f"limit must be int, not {type(limit).__name__}")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return [
            {
                "name": function.name,
                "description": function.description,
                "stub": function.stub,
            }
            for function in self.search(query, min(limit, MAX_TOOL_SEARCH_LIMIT))
        ]
