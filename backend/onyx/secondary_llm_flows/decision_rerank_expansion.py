"""Internal search decisions made with the configured decision model.

Ranking asks one yes/no question per section in a single request, so the model
compares the sections with each other. Probabilities from separate requests are
not comparable, so all candidates go into one request.
"""

from onyx.context.search.models import ContextExpansionType, InferenceSection
from onyx.llm.decisions.client import DecisionClient
from onyx.llm.decisions.models import (
    DecisionQuestion,
    DecisionRequest,
    PredicateAnswer,
    PredicateQuestion,
    RefusalAnswer,
    ScoreAnswer,
    ScoreLevel,
    ScoreQuestion,
)
from onyx.prompts.search_prompts import (
    DECISION_EXPANSION_LEVELS,
    DECISION_EXPANSION_QUESTION,
    DECISION_RERANK_QUESTION,
)
from onyx.secondary_llm_flows.document_filter import select_chunks_for_relevance
from onyx.tools.tool_implementations.search.constants import MAX_CHUNKS_FOR_RELEVANCE
from onyx.tracing.flows import LLMFlow

# A decision request takes at most this many questions.
MAX_DECISION_QUESTIONS = 200

# Expansion levels in the order of DECISION_EXPANSION_LEVELS.
_EXPANSION_TYPES = [
    ContextExpansionType.NOT_RELEVANT,
    ContextExpansionType.MAIN_SECTION_ONLY,
    ContextExpansionType.INCLUDE_ADJACENT_SECTIONS,
    ContextExpansionType.FULL_DOCUMENT,
]

_EXPANSION_QUESTION = ScoreQuestion(
    name="expansion",
    instructions=DECISION_EXPANSION_QUESTION,
    levels=[
        ScoreLevel(label=label, description=description)
        for label, description in DECISION_EXPANSION_LEVELS
    ],
)


def _section_text(section: InferenceSection) -> str:
    return " ".join(
        chunk.content
        for chunk in select_chunks_for_relevance(section, MAX_CHUNKS_FOR_RELEVANCE)
    )


def rank_sections_listwise(
    sections: list[InferenceSection],
    user_query: str,
    client: DecisionClient,
) -> list[float]:
    """Return one probability per section that it is among the sections that
    best help answer the query. Raises when the call fails or the model refuses
    every question."""
    if not sections:
        return []
    if len(sections) > MAX_DECISION_QUESTIONS:
        raise ValueError(f"At most {MAX_DECISION_QUESTIONS} sections fit one request")
    blocks = [f"Query: {user_query}"]
    for index, section in enumerate(sections):
        blocks.append(
            f"[{index}] Document: {section.center_chunk.semantic_identifier}\n"
            f"{_section_text(section)}"
        )
    questions: list[DecisionQuestion] = [
        PredicateQuestion(
            name=f"s{index}",
            instructions=DECISION_RERANK_QUESTION.format(index=index),
        )
        for index in range(len(sections))
    ]
    response = client.decide(
        DecisionRequest(input="\n\n".join(blocks), questions=questions),
        flow=LLMFlow.SEARCH_SECTION_RERANK,
    )
    if all(isinstance(answer, RefusalAnswer) for answer in response.answers):
        raise ValueError("Decision model refused every ranking question")
    # A refusal ranks the section last.
    return [
        answer.probability if isinstance(answer, PredicateAnswer) else 0.0
        for answer in response.answers
    ]


def decide_context_expansion(
    document_title: str,
    section_text: str,
    user_query: str,
    client: DecisionClient,
    section_above_text: str | None,
    section_below_text: str | None,
) -> ContextExpansionType:
    """Pick the most likely expansion level. Raises when the call fails or the
    model refuses."""
    request_input = "\n".join(
        [
            f"Query: {user_query}",
            "",
            f"Document: {document_title}",
            "Section above:",
            section_above_text or "N/A",
            "Main section:",
            section_text,
            "Section below:",
            section_below_text or "N/A",
        ]
    )
    response = client.decide(
        DecisionRequest(input=request_input, questions=[_EXPANSION_QUESTION]),
        flow=LLMFlow.SEARCH_CONTEXT_EXPANSION_DECISION,
    )
    answer = response.answers[0]
    if not isinstance(answer, ScoreAnswer):
        raise ValueError("Decision model refused the expansion question")
    best = max(answer.probabilities, key=lambda item: item.probability)
    classification = _EXPANSION_TYPES[best.value]
    # Without neighbors there is nothing to add around the section.
    if (
        not section_above_text
        and not section_below_text
        and classification != ContextExpansionType.NOT_RELEVANT
    ):
        return ContextExpansionType.MAIN_SECTION_ONLY
    return classification
