"""tool_search(): how programs find the deferred functions, which the
`execute_code` description does not list."""

import math
import re
from collections import Counter
from collections.abc import Sequence

from onyx.tools.tool_implementations.code_mode.models import SearchableFunction
from onyx.tools.tool_implementations.code_mode.sandbox import TOOLS_NAMESPACE

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
    """Find tool functions that this description does not list, best match first.

    Each match has the function name, its description, and its full stub with
    the argument and result types. Call a match as `await {TOOLS_NAMESPACE}.<name>(...)`.
    At most `limit` matches, up to {MAX_TOOL_SEARCH_LIMIT}.
    """
    ...'''

# Runs of letters and digits in any script; `_` and other symbols split words.
_TOKEN = re.compile(r"[^\W_]+")
# BM25 parameters: term frequency saturation and document length normalization.
_K1 = 1.2
_B = 0.75
# Parameter text counts at this weight against name, namespace and description
# text. BM25 scores the two apart, so a large schema does not dilute a name or
# description match.
PARAMETER_WEIGHT = 0.5


def _tokens(text: str) -> list[str]:
    # Splits snake_case, kebab-case and camelCase names into words.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return _TOKEN.findall(spaced.lower())


class _Bm25:
    """BM25 scores of one text field across the deferred functions."""

    def __init__(self, texts: Sequence[str]) -> None:
        self._terms = [Counter(_tokens(text)) for text in texts]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        frequencies = Counter(term for terms in self._terms for term in terms)
        count = len(self._terms)
        self._idf = {
            term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in frequencies.items()
        }

    def scores(self, query_terms: set[str]) -> list[float]:
        result: list[float] = []
        for index, terms in enumerate(self._terms):
            length_norm = (
                1 - _B + _B * self._lengths[index] / (self._average_length or 1.0)
            )
            result.append(
                sum(
                    self._idf[term]
                    * terms[term]
                    * (_K1 + 1)
                    / (terms[term] + _K1 * length_norm)
                    for term in query_terms
                    if term in terms
                )
            )
        return result


class ToolIndex:
    """BM25 ranking over the deferred functions of one program."""

    def __init__(self, functions: Sequence[SearchableFunction]) -> None:
        self._functions = list(functions)
        self._main = _Bm25([function.text for function in functions])
        self._parameters = _Bm25([function.parameter_text for function in functions])

    def search(self, query: str, limit: int) -> list[SearchableFunction]:
        query_terms = set(_tokens(query))
        scored = [
            (main + PARAMETER_WEIGHT * parameters, function)
            for main, parameters, function in zip(
                self._main.scores(query_terms),
                self._parameters.scores(query_terms),
                self._functions,
                strict=True,
            )
            if main > 0 or parameters > 0
        ]
        # Ties keep name order.
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [function for _, function in scored[:limit]]

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
