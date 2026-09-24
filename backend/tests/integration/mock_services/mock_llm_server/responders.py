"""Default answers for the tool-less secondary LLM calls a chat turn, a search,
or Deep Research can make, so a script only has to cover the turns under test.

Each responder matches a request that offers no tools and whose system/user
text contains every one of its markers. The markers are fixed phrases from the
Onyx prompt of that flow; the unit tests run each real flow against this server
to prove that the markers still match and that the answers still parse.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from tests.integration.mock_services.mock_llm_server.models import RecordedRequest


class Builtin(StrEnum):
    SEMANTIC_QUERY_REPHRASE = "semantic_query_rephrase"
    KEYWORD_QUERY_EXPANSION = "keyword_query_expansion"
    SOURCE_FILTER = "source_filter"
    TIME_FILTER = "time_filter"
    SECTION_SELECTION = "section_selection"
    SECTION_RELEVANCE = "section_relevance"
    MEMORY_UPDATE = "memory_update"
    CHAT_SESSION_NAMING = "chat_session_naming"
    CHAT_HISTORY_SUMMARY = "chat_history_summary"
    SEARCH_FLOW_CLASSIFICATION = "search_flow_classification"
    SEARCH_KEYWORD_EXPANSION = "search_keyword_expansion"
    CONNECTION_TEST = "connection_test"


MOCK_CHAT_SESSION_NAME = "Mock Chat"
MOCK_HISTORY_SUMMARY = "Summary of the earlier conversation."
CONNECTION_TEST_PROMPT = "Do not respond"

_FINAL_USER_QUERY = "Final user query:"
_THE_USER_QUERY_IS = "The user query is:"
_SECTION_ID_RE = re.compile(r'"section_id":\s*(\d+)')
_MAX_SECTIONS_RE = re.compile(r"\(maximum (\d+)\)")


def _last_user_text(request: RecordedRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return ""


def _text_after(request: RecordedRequest, label: str) -> str:
    text = _last_user_text(request)
    if label in text:
        text = text.rsplit(label, 1)[1]
    return text.strip() or "mock query"


def _select_all_sections(request: RecordedRequest) -> str:
    text = _last_user_text(request)
    section_ids = list(dict.fromkeys(_SECTION_ID_RE.findall(text)))
    max_match = _MAX_SECTIONS_RE.search(text)
    if max_match is not None:
        section_ids = section_ids[: int(max_match.group(1))]
    return "[" + ", ".join(section_ids or ["0"]) + "]"


def _is_connection_test(request: RecordedRequest) -> bool:
    return (
        len(request.messages) == 1
        and request.messages[0].role == "user"
        and request.messages[0].content.strip() == CONNECTION_TEST_PROMPT
    )


@dataclass(frozen=True)
class BuiltinResponder:
    name: Builtin
    markers: tuple[str, ...]
    respond: Callable[[RecordedRequest], str]
    predicate: Callable[[RecordedRequest], bool] | None = None

    def matches(self, request: RecordedRequest) -> bool:
        if request.tools:
            return False
        if self.predicate is not None:
            return self.predicate(request)
        prompt_text = request.prompt_text
        return all(marker in prompt_text for marker in self.markers)


BUILTIN_RESPONDERS: tuple[BuiltinResponder, ...] = (
    # Echo the query so the search runs on what the user typed.
    BuiltinResponder(
        name=Builtin.SEMANTIC_QUERY_REPHRASE,
        markers=(
            "reformulates the last user message into a standalone, self-contained query",
        ),
        respond=lambda r: _text_after(r, _FINAL_USER_QUERY),
    ),
    BuiltinResponder(
        name=Builtin.KEYWORD_QUERY_EXPANSION,
        markers=(
            "reformulates the last user message into a set of standalone keyword queries",
        ),
        respond=lambda r: _text_after(r, _FINAL_USER_QUERY),
    ),
    # An empty list means "no source scope".
    BuiltinResponder(
        name=Builtin.SOURCE_FILTER,
        markers=("You scope an internal search to its relevant sources.",),
        respond=lambda _r: "[]",
    ),
    BuiltinResponder(
        name=Builtin.TIME_FILTER,
        markers=("You scope an internal search to a time filter",),
        respond=lambda _r: "updated (None, None)",
    ),
    # Keep every candidate section, in the order given.
    BuiltinResponder(
        name=Builtin.SECTION_SELECTION,
        markers=("Select the most relevant document sections for the user's query",),
        respond=_select_all_sections,
    ),
    # 1 = MAIN_SECTION_ONLY.
    BuiltinResponder(
        name=Builtin.SECTION_RELEVANCE,
        markers=("Analyze the relevance of document sections to a search query",),
        respond=lambda _r: "1",
    ),
    # Without memory_text the flow stores the new memory as given.
    BuiltinResponder(
        name=Builtin.MEMORY_UPDATE,
        markers=("You are a memory update agent",),
        respond=lambda _r: '{"operation": "add", "memory_id": null}',
    ),
    BuiltinResponder(
        name=Builtin.CHAT_SESSION_NAMING,
        markers=("provide a SHORT name for the conversation",),
        respond=lambda _r: MOCK_CHAT_SESSION_NAME,
    ),
    BuiltinResponder(
        name=Builtin.CHAT_HISTORY_SUMMARY,
        markers=("You are a summarization system.",),
        respond=lambda _r: MOCK_HISTORY_SUMMARY,
    ),
    BuiltinResponder(
        name=Builtin.SEARCH_FLOW_CLASSIFICATION,
        markers=("better suited for a search UI or a chat UI",),
        respond=lambda _r: "search",
    ),
    # Answering with the query itself means "no useful expansions".
    BuiltinResponder(
        name=Builtin.SEARCH_KEYWORD_EXPANSION,
        markers=(
            "Generate a set of keyword-only queries to help find relevant documents",
        ),
        respond=lambda r: _text_after(r, _THE_USER_QUERY_IS),
    ),
    BuiltinResponder(
        name=Builtin.CONNECTION_TEST,
        markers=(),
        respond=lambda _r: "OK",
        predicate=_is_connection_test,
    ),
)


def find_builtin(
    request: RecordedRequest, disabled: set[str]
) -> BuiltinResponder | None:
    for responder in BUILTIN_RESPONDERS:
        if responder.name.value in disabled:
            continue
        if responder.matches(request):
            return responder
    return None
