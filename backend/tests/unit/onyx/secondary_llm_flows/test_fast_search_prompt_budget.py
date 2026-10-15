import json
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.secondary_llm_flows.query_expansion import expand_keywords
from ee.onyx.secondary_llm_flows.search_flow_classification import (
    classify_is_search_flow,
)
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.federated.slack_search_utils import (
    expand_query_with_llm,
    extract_date_range_from_query,
)
from onyx.context.search.models import (
    ContextExpansionType,
    InferenceChunk,
    InferenceSection,
)
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ThinkingContent,
)
from onyx.llm.token_budget import TokenBudget
from onyx.secondary_llm_flows.document_filter import (
    classify_section_relevance,
    select_sections_for_expansion,
)
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.secondary_llm_flows.source_filter import decide_search_scope
from onyx.secondary_llm_flows.time_filter import decide_time_filter
from onyx.tools.models import ChatMinimalTextMessage


def _llm(response: str, max_input_tokens: int = 4096) -> MagicMock:
    llm = MagicMock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        temperature=0,
        max_input_tokens=max_input_tokens,
    )
    llm.invoke.return_value = AssistantMessage(content=[TextContent(text=response)])
    return llm


def _reasoning_llm(response: str, max_input_tokens: int = 4096) -> MagicMock:
    llm = _llm(response, max_input_tokens)

    def invoke(request: GenerationRequest, **_context: object) -> AssistantMessage:
        if request.options.max_tokens is not None and request.options.max_tokens <= 512:
            return AssistantMessage(
                content=[ThinkingContent(text="Compare the evidence.")]
            )
        return AssistantMessage(content=[TextContent(text=response)])

    llm.invoke.side_effect = invoke
    return llm


def _section(index: int, content: str) -> InferenceSection:
    chunk = InferenceChunk(
        document_id=f"doc-{index}",
        chunk_id=0,
        content=content,
        source_type=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"Document {index}",
        title=f"Document {index}",
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
        blurb="body",
        file_id=None,
    )
    return InferenceSection(
        center_chunk=chunk, chunks=[chunk], combined_content=content
    )


def _assert_request_fits(llm: MagicMock) -> GenerationRequest:
    request: GenerationRequest = llm.invoke.call_args.args[0]
    token_count = get_llm_token_counter(llm)(request.model_dump_json(exclude_none=True))
    assert request.options.max_tokens is not None
    assert token_count + request.options.max_tokens <= llm.config.max_input_tokens
    assert request.options.reasoning_effort == ReasoningEffort.OFF
    return request


def test_selection_caps_serialized_metadata_and_preserves_full_evidence() -> None:
    first = _section(0, "onboarding evidence " * 12000)
    first.center_chunk.metadata = {"large": ["metadata " * 12000]}
    second = _section(1, "other evidence")
    llm = _llm("[0]")

    selected, best = select_sections_for_expansion(
        [first, second], "Find onboarding steps", llm, enforce_llm_input_budget=True
    )

    assert selected == [first]
    assert best is None
    request = _assert_request_fits(llm)
    text = request.messages[0].content
    assert isinstance(text, str)
    assert "Find onboarding steps" in text
    documents = json.loads(text.split("```", 2)[1])
    assert [doc["section_id"] for doc in documents] == [0]
    assert set(documents[0]) == {"section_id", "title", "source_type", "content"}
    assert documents[0]["content"].startswith("onboarding evidence")
    assert first.combined_content == "onboarding evidence " * 12000


def test_selection_omits_oversized_title_only_from_utility_prompt() -> None:
    section = _section(0, "onboarding evidence")
    section.center_chunk.semantic_identifier = "Long title " * 12000
    llm = _llm("[0]")

    selected, best = select_sections_for_expansion(
        [section], "Find onboarding steps", llm, enforce_llm_input_budget=True
    )

    assert selected == [section]
    assert best is None
    request = _assert_request_fits(llm)
    text = str(request.messages[0].content)
    documents = json.loads(text.split("```", 2)[1])
    assert documents[0]["title"] == ""
    assert documents[0]["content"] == "onboarding evidence"
    assert section.center_chunk.semantic_identifier == "Long title " * 12000


def test_selection_unset_budget_keeps_all_serialized_candidates() -> None:
    sections = [_section(0, "first body " * 6000), _section(1, "second body")]
    llm = _llm("[1,0]")

    selected, _ = select_sections_for_expansion(sections, "query", llm)

    assert selected == [sections[1], sections[0]]
    request: GenerationRequest = llm.invoke.call_args.args[0]
    assert request.options.max_tokens is None
    assert "second body" in str(request.messages[0].content)
    assert "first body " * 6000 in str(request.messages[0].content)


@pytest.mark.parametrize(
    "max_input_tokens, context_tokens, safety_tokens, expected_output_tokens",
    [
        (32768, 32768, 0, 4096),
        (4096, None, 0, 1024),
        (65536, 4096, 64, 1008),
    ],
)
def test_selection_allows_reasoning_without_consuming_context(
    max_input_tokens: int,
    context_tokens: int | None,
    safety_tokens: int,
    expected_output_tokens: int,
) -> None:
    sections = [_section(0, "unrelated evidence"), _section(1, "onboarding steps")]
    llm = _reasoning_llm("[1]", max_input_tokens)
    native_budget = TokenBudget(
        input_tokens=max_input_tokens,
        max_output_tokens=128000,
        context_tokens=context_tokens,
        safety_tokens=safety_tokens,
    )

    with patch(
        "onyx.secondary_llm_flows.search_prompt_budget.resolve_token_budget",
        return_value=native_budget,
    ):
        selected, best = select_sections_for_expansion(
            sections,
            "Find onboarding steps",
            llm,
            max_sections=1,
            enforce_llm_input_budget=True,
        )

    assert selected == [sections[1]]
    assert best is None
    request = _assert_request_fits(llm)
    assert request.options.max_tokens == expected_output_tokens
    if context_tokens is not None:
        input_tokens = get_llm_token_counter(llm)(
            request.model_dump_json(exclude_none=True)
        )
        assert input_tokens + expected_output_tokens + safety_tokens <= context_tokens


def test_selection_reserves_native_output_and_context_capacity() -> None:
    section = _section(0, "evidence " * 12000)
    llm = _llm("[0]", max_input_tokens=65536)
    native_budget = TokenBudget(
        input_tokens=65500, max_output_tokens=128, context_tokens=4096, safety_tokens=64
    )
    with patch(
        "onyx.secondary_llm_flows.search_prompt_budget.resolve_token_budget",
        return_value=native_budget,
    ):
        selected, _ = select_sections_for_expansion(
            [section], "query", llm, enforce_llm_input_budget=True
        )

    assert selected == [section]
    request = _assert_request_fits(llm)
    input_tokens = get_llm_token_counter(llm)(
        request.model_dump_json(exclude_none=True)
    )
    assert request.options.max_tokens == 128
    assert input_tokens + 128 + 64 <= 4096


def test_selection_fixed_prompt_too_large_uses_original_sections() -> None:
    sections = [_section(0, "first"), _section(1, "second")]
    llm = _llm("[1]")

    selected, _ = select_sections_for_expansion(
        sections,
        "oversized query " * 12000,
        llm,
        max_sections=1,
        enforce_llm_input_budget=True,
    )

    assert selected == [sections[0]]
    llm.invoke.assert_not_called()


def test_classification_caps_section_and_retains_question() -> None:
    llm = _llm("1")

    classification = classify_section_relevance(
        "Runbook",
        "main evidence " * 12000,
        "Find onboarding steps",
        llm,
        "above " * 12000,
        "below " * 12000,
        enforce_llm_input_budget=True,
    )

    assert classification == ContextExpansionType.MAIN_SECTION_ONLY
    request = _assert_request_fits(llm)
    text = str(request.messages[0].content)
    assert "Runbook" in text
    assert "Find onboarding steps" in text
    assert "main evidence" in text
    assert "above above" not in text
    assert "# Section Above:\n```\nN/A\n```" in text
    assert "# Section Below:\n```\nN/A\n```" in text


@pytest.mark.parametrize("keyword", [False, True])
def test_rewriting_drops_old_history_and_memories_before_current_query(
    keyword: bool,
) -> None:
    llm = _llm("onboarding steps")
    history = [
        ChatMinimalTextMessage(
            message="old history " * 12000, message_type=MessageType.USER
        ),
        ChatMinimalTextMessage(
            message="old answer " * 12000, message_type=MessageType.ASSISTANT
        ),
        ChatMinimalTextMessage(
            message="Find onboarding steps", message_type=MessageType.USER
        ),
    ]
    rewrite = keyword_query_expansion if keyword else semantic_query_rephrase

    result = rewrite(
        history,
        llm,
        user_info="profile " * 12000,
        memories=["memory " * 12000],
        enforce_llm_input_budget=True,
    )

    assert result == (["onboarding steps"] if keyword else "onboarding steps")
    request = _assert_request_fits(llm)
    assert len(request.messages) == 2
    assert "Find onboarding steps" in str(request.messages[-1].content)
    assert "memory memory" not in str(request.messages[-1].content)
    assert history[0].message == "old history " * 12000


def test_oversized_rewrite_query_falls_back_without_provider_call() -> None:
    llm = _llm("rewritten")
    query = "oversized question " * 12000
    history = [ChatMinimalTextMessage(message=query, message_type=MessageType.USER)]

    semantic = semantic_query_rephrase(history, llm, enforce_llm_input_budget=True)
    keywords = keyword_query_expansion(history, llm, enforce_llm_input_budget=True)

    assert semantic == query
    assert keywords == []
    llm.invoke.assert_not_called()


def test_oversized_filter_prompts_fail_open_without_provider_call() -> None:
    llm = _llm("[slack]")
    history = [
        ChatMinimalTextMessage(message="query " * 12000, message_type=MessageType.USER)
    ]

    scope = decide_search_scope(
        history,
        llm,
        [DocumentSource.SLACK, DocumentSource.GOOGLE_DRIVE],
        [],
        ["query"],
        enforce_llm_input_budget=True,
    )
    time_filter = decide_time_filter(history, llm, enforce_llm_input_budget=True)

    assert scope is None
    assert time_filter is None
    llm.invoke.assert_not_called()


def test_ee_small_prompts_fit_and_oversized_queries_use_local_defaults() -> None:
    llm = _llm("onboarding checklist")
    assert expand_keywords("onboarding", llm, enforce_llm_input_budget=True) == [
        "onboarding checklist"
    ]
    _assert_request_fits(llm)
    llm.invoke.reset_mock()
    assert expand_keywords("query " * 12000, llm, enforce_llm_input_budget=True) == []
    assert (
        classify_is_search_flow("query " * 12000, llm, enforce_llm_input_budget=True)
        is False
    )
    llm.invoke.assert_not_called()


def test_ee_fast_keywords_allow_reasoning_before_visible_response() -> None:
    keyword_llm = _reasoning_llm("onboarding checklist")
    assert expand_keywords(
        "onboarding", keyword_llm, enforce_llm_input_budget=True
    ) == ["onboarding checklist"]
    _assert_request_fits(keyword_llm)


def test_ee_fast_classification_allows_reasoning_before_visible_response() -> None:
    classification_llm = _reasoning_llm("search")
    assert classify_is_search_flow(
        "onboarding", classification_llm, enforce_llm_input_budget=True
    )
    _assert_request_fits(classification_llm)


def test_ee_unset_fast_keeps_existing_output_caps() -> None:
    keyword_llm = _llm("onboarding checklist")
    assert expand_keywords("onboarding", keyword_llm) == ["onboarding checklist"]
    assert _assert_request_fits(keyword_llm).options.max_tokens == 150

    classification_llm = _llm("search")
    assert classify_is_search_flow("onboarding", classification_llm)
    assert _assert_request_fits(classification_llm).options.max_tokens == 20


def test_slack_query_expansion_without_fast_preserves_default_options() -> None:
    llm = _llm("onboarding checklist")
    expanded = expand_query_with_llm("onboarding", llm)
    expansion_request: GenerationRequest = llm.invoke.call_args.args[0]
    assert expanded == ["onboarding checklist"]
    assert expansion_request.options.model_dump(exclude_none=True) == {
        "tool_choice": "auto",
        "reasoning_effort": "auto",
    }


def test_slack_date_prompt_keeps_existing_local_fallback() -> None:
    llm = _llm('{"days_back": 12}')
    days = extract_date_range_from_query("onboarding before launch", llm, 30)
    assert days == 30
    llm.invoke.assert_not_called()


def test_slack_query_expansion_caps_oversized_original_query() -> None:
    llm = _llm("onboarding checklist")
    expanded = expand_query_with_llm(
        "onboarding " * 12000, llm, enforce_llm_input_budget=True
    )

    assert expanded == ["onboarding checklist"]
    request = _assert_request_fits(llm)
    assert "onboarding onboarding" in str(request.messages[0].content)
