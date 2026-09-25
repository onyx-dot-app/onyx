"""Runs each real secondary LLM flow against the mock LLM server.

The script has no lanes, so a request only succeeds if a built-in responder
recognizes the real Onyx prompt. The flow's own parsing then proves that the
answer is usable. Several flows fail open to the same value a parse failure
would give; for those the responder's text also goes through the flow's parser.
"""

from ee.onyx.secondary_llm_flows.query_expansion import expand_keywords
from ee.onyx.secondary_llm_flows.search_flow_classification import (
    classify_is_search_flow,
)
from onyx.chat.compression import generate_summary
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import (
    ContextExpansionType,
    InferenceChunk,
    InferenceSection,
)
from onyx.db.models import ChatMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.utils import test_llm as run_llm_connection_test
from onyx.secondary_llm_flows.chat_session_naming import generate_chat_session_name
from onyx.secondary_llm_flows.document_filter import (
    _parse_section_ids,
    classify_section_relevance,
    select_sections_for_expansion,
)
from onyx.secondary_llm_flows.memory_update import process_memory_update
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.secondary_llm_flows.source_filter import (
    _parse_scope_decision,
    decide_search_scope,
)
from onyx.secondary_llm_flows.time_filter import (
    _parse_time_decision,
    decide_time_filter,
)
from onyx.tools.models import ChatMinimalTextMessage
from onyx.utils.text_processing import parse_llm_json_response
from tests.integration.mock_services.mock_llm_server.handle import ScriptHandle
from tests.integration.mock_services.mock_llm_server.models import RecordedRequest
from tests.integration.mock_services.mock_llm_server.responders import (
    BUILTIN_RESPONDERS,
    MOCK_CHAT_SESSION_NAME,
    MOCK_HISTORY_SUMMARY,
    Builtin,
)

QUERY = "What is our PTO policy?"
HISTORY = [ChatMinimalTextMessage(message=QUERY, message_type=MessageType.USER)]
SOURCES = [DocumentSource.SLACK, DocumentSource.GOOGLE_DRIVE]


def _served_by(script: ScriptHandle, builtin: Builtin) -> RecordedRequest:
    requests = script.requests
    assert [r.builtin for r in requests] == [builtin.value]
    assert requests[0].error is None
    script.verify()
    return requests[0]


def _answer(builtin: Builtin, request: RecordedRequest) -> str:
    (responder,) = [r for r in BUILTIN_RESPONDERS if r.name == builtin]
    return responder.respond(request)


def _section(index: int) -> InferenceSection:
    chunk = InferenceChunk(
        document_id=f"doc-{index}",
        chunk_id=0,
        content=f"section {index}",
        source_type=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"doc-{index}",
        title=f"doc-{index}",
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb="blurb",
        file_id=None,
    )
    return InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content=chunk.content
    )


def test_semantic_query_rephrase(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert semantic_query_rephrase(HISTORY, llm) == QUERY
    _served_by(script, Builtin.SEMANTIC_QUERY_REPHRASE)


def test_keyword_query_expansion(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert keyword_query_expansion(HISTORY, llm) == [QUERY]
    _served_by(script, Builtin.KEYWORD_QUERY_EXPANSION)


def test_source_filter(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert decide_search_scope(HISTORY, llm, SOURCES, [], [QUERY]) is None
    request = _served_by(script, Builtin.SOURCE_FILTER)
    assert _answer(Builtin.SOURCE_FILTER, request) == "[]"
    assert _parse_scope_decision("[slack]", SOURCES) == [DocumentSource.SLACK]


def test_source_filter_override_is_parsed(
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.set_builtin(Builtin.SOURCE_FILTER, "[slack]")
    assert decide_search_scope(HISTORY, llm, SOURCES, [], [QUERY]) == [
        DocumentSource.SLACK
    ]


def test_time_filter(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert decide_time_filter(HISTORY, llm) is None
    request = _served_by(script, Builtin.TIME_FILTER)
    answer = _answer(Builtin.TIME_FILTER, request)
    assert _parse_time_decision(answer) is None
    assert _parse_time_decision(answer.replace("None, None", "2024-01-01, None"))


def test_section_selection(script: ScriptHandle, llm: LitellmLLM) -> None:
    sections = [_section(i) for i in range(3)]

    selected, _ = select_sections_for_expansion(sections, QUERY, llm, max_sections=2)

    assert selected == sections[:2]
    request = _served_by(script, Builtin.SECTION_SELECTION)
    assert _parse_section_ids(_answer(Builtin.SECTION_SELECTION, request)) == (
        ["0", "1"],
        set(),
    )


def test_section_relevance(script: ScriptHandle, llm: LitellmLLM) -> None:
    classification = classify_section_relevance(
        document_title="doc",
        section_text="main",
        user_query=QUERY,
        llm=llm,
        section_above_text="above",
        section_below_text="below",
    )

    assert classification == ContextExpansionType.MAIN_SECTION_ONLY
    _served_by(script, Builtin.SECTION_RELEVANCE)


def test_section_relevance_override_is_parsed(
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.set_builtin(Builtin.SECTION_RELEVANCE, "2")
    classification = classify_section_relevance(
        document_title="doc",
        section_text="main",
        user_query=QUERY,
        llm=llm,
        section_above_text="above",
        section_below_text="below",
    )
    assert classification == ContextExpansionType.INCLUDE_ADJACENT_SECTIONS


def test_memory_update(script: ScriptHandle, llm: LitellmLLM) -> None:
    result = process_memory_update(
        new_memory="Prefers dark mode.",
        existing_memories=["Likes tea."],
        chat_history=HISTORY,
        llm=llm,
    )

    assert result == ("Prefers dark mode.", None)
    request = _served_by(script, Builtin.MEMORY_UPDATE)
    parsed = parse_llm_json_response(_answer(Builtin.MEMORY_UPDATE, request))
    assert parsed is not None and parsed["operation"] == "add"


def test_chat_session_naming(script: ScriptHandle, llm: LitellmLLM) -> None:
    history = [
        ChatMessageSimple(message=QUERY, token_count=8, message_type=MessageType.USER)
    ]

    assert generate_chat_session_name(history, llm) == MOCK_CHAT_SESSION_NAME
    _served_by(script, Builtin.CHAT_SESSION_NAMING)


def test_chat_history_summary(script: ScriptHandle, llm: LitellmLLM) -> None:
    older = [
        ChatMessage(message=QUERY, message_type=MessageType.USER),
        ChatMessage(message="It is 20 days.", message_type=MessageType.ASSISTANT),
    ]

    summary = generate_summary(
        older_messages=older, recent_messages=[], llm=llm, tool_id_to_name={}
    )

    assert summary == MOCK_HISTORY_SUMMARY
    _served_by(script, Builtin.CHAT_HISTORY_SUMMARY)


def test_search_flow_classification(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert classify_is_search_flow(QUERY, llm) is True
    _served_by(script, Builtin.SEARCH_FLOW_CLASSIFICATION)


def test_search_keyword_expansion(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert expand_keywords(QUERY, llm) == []
    request = _served_by(script, Builtin.SEARCH_KEYWORD_EXPANSION)
    assert _answer(Builtin.SEARCH_KEYWORD_EXPANSION, request) == QUERY


def test_search_keyword_expansion_override_is_parsed(
    script: ScriptHandle, llm: LitellmLLM
) -> None:
    script.set_builtin(Builtin.SEARCH_KEYWORD_EXPANSION, "pto\nvacation policy")
    assert expand_keywords(QUERY, llm) == ["pto", "vacation policy"]


def test_connection_test(script: ScriptHandle, llm: LitellmLLM) -> None:
    assert run_llm_connection_test(llm) is None
    _served_by(script, Builtin.CONNECTION_TEST)
