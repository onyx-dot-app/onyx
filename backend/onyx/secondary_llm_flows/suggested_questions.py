"""Triage for suggested questions: a decision model reads a short snippet of
each chunk and says whether it is worth a question, whether it is private,
which kind of work it fits, and whether it states a concrete fact.

Like the search reranker, a request numbers many chunks inside one input and
asks typed questions about each, so there is no text to parse.

Then one call to a small model writes questions about the best passages.
"""

import logging
import re
from collections import Counter

import httpx

from onyx.context.search.models import InferenceChunk
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.llm.decisions.client import DecisionClient
from onyx.llm.decisions.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionAnswer,
    DecisionChoice,
    DecisionProvider,
    DecisionQuestion,
    DecisionRequest,
    PredicateAnswer,
    PredicateQuestion,
    RefusalAnswer,
    ScoreAnswer,
    ScoreLevel,
    ScoreQuestion,
)
from onyx.llm.factory import get_decision_client_for_provider, get_llm_for_provider
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    ReasoningEffort,
    SystemMessage,
    UserMessage,
)
from onyx.prompts.suggested_questions import (
    SQ_TRIAGE_FACT_QUESTION,
    SQ_TRIAGE_SENSITIVE_QUESTION,
    SQ_TRIAGE_TOPIC_CHOICES,
    SQ_TRIAGE_TOPIC_QUESTION,
    SQ_TRIAGE_USABLE_LEVELS,
    SQ_TRIAGE_USABLE_QUESTION,
    SQ_WRITING_SYSTEM_PROMPT,
)
from onyx.server.features.suggested_questions.config import (
    SQ_LLM_TIMEOUT_S,
    SQ_PASSAGE_CHARS,
    SQ_PASSAGES_MAX,
    SQ_QUESTION_MAX_CHARS,
    SQ_QUESTIONS_PER_PASSAGE,
    SQ_QUESTIONS_PER_RUN,
    SQ_RULES_MAX_CHUNK_ID,
    SQ_TRIAGE_CHUNKS_PER_REQUEST,
    SQ_TRIAGE_MIN_SCORE,
    SQ_TRIAGE_OPENAI_MODEL,
    SQ_TRIAGE_SENSITIVE_MAX,
    SQ_TRIAGE_SNIPPET_CHARS,
    SQ_TRIAGE_WORKERS,
    SQ_TRIAGE_ZOOM_MODEL,
    SQ_WRITING_ANTHROPIC_MODEL,
    SQ_WRITING_MAX_TOKENS,
    SQ_WRITING_OPENAI_MODEL,
)
from onyx.server.features.suggested_questions.models import (
    DraftQuestion,
    TriagedChunk,
    UseCase,
    WritingOutput,
    WrittenQuestion,
)
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

_USABLE_LEVELS = [
    ScoreLevel(label=label, description=description)
    for label, description in SQ_TRIAGE_USABLE_LEVELS
]
_TOPIC_CHOICES = [
    DecisionChoice(value=value, description=description)
    for value, description in SQ_TRIAGE_TOPIC_CHOICES
]

# Rules-only fallback. A chunk needs a digit or a capitalized word inside a
# sentence (a name), and none of these words.
_CONCRETE = re.compile(r"\d|\b[a-z]+ [A-Z][a-z]+")
_SENSITIVE_WORDS = re.compile(
    r"\b(salary|salaries|compensation|payroll|bonus|diagnos\w*|medical|"
    r"performance reviews?|passwords?|social security)\b",
    re.IGNORECASE,
)


class _RefusedEverything(Exception):
    """The decision model refused every question in a request."""


def build_triage_clients() -> list[DecisionClient]:
    """OpenAI first, then Zoom. A provider the tenant has not set up is
    skipped.

    The models are fixed in code because this runs only on the Playground,
    where we set up every tenant's providers. Before it runs for other
    deployments, try the admin's decision model first (get_decision_client):
    their setup may have no OpenAI or Zoom provider."""
    clients = []
    for provider, model in (
        (DecisionProvider.OPENAI, SQ_TRIAGE_OPENAI_MODEL),
        (DecisionProvider.ZOOM_AI, SQ_TRIAGE_ZOOM_MODEL),
    ):
        try:
            client = get_decision_client_for_provider(provider, model)
        except (OnyxError, ValueError):
            # Over the cost limit, or set up wrong: try the next provider.
            logger.warning(
                "Suggested questions: cannot use %s for triage",
                provider.value,
                exc_info=True,
            )
            continue
        if client is not None:
            clients.append(client)
    return clients


def triage_chunks(
    chunks: list[InferenceChunk], clients: list[DecisionClient]
) -> list[TriagedChunk]:
    """Score the chunks and return the ones worth a question and not private.
    The requests run in parallel. Each tries the clients in order, and falls
    back to cheap rules when every client fails."""
    batches = [
        chunks[start : start + SQ_TRIAGE_CHUNKS_PER_REQUEST]
        for start in range(0, len(chunks), SQ_TRIAGE_CHUNKS_PER_REQUEST)
    ]
    results: list[tuple[str, list[TriagedChunk]]] = run_functions_tuples_in_parallel(
        [(_triage_batch, (batch, clients)) for batch in batches],
        max_workers=SQ_TRIAGE_WORKERS,
    )
    scored = [triaged for _, batch_result in results for triaged in batch_result]
    useful = [item for item in scored if item.usable >= SQ_TRIAGE_MIN_SCORE]
    kept = [item for item in useful if item.sensitive < SQ_TRIAGE_SENSITIVE_MAX]
    sources = Counter(source for source, _ in results)
    # A warning when no provider answered for a batch, or nothing was kept.
    logger.log(
        (
            logging.WARNING
            if sources["rules"] or sources["refused"] or (scored and not kept)
            else logging.INFO
        ),
        "Suggested questions: triaged %d chunks in %d requests (answered by %s), "
        "kept %d, dropped %d not useful and %d sensitive",
        len(scored),
        len(batches),
        dict(sources),
        len(kept),
        len(scored) - len(useful),
        len(useful) - len(kept),
    )
    return kept


def _triage_batch(
    batch: list[InferenceChunk], clients: list[DecisionClient]
) -> tuple[str, list[TriagedChunk]]:
    """The scored batch, and which provider answered: its name, "refused" or
    "rules"."""
    refused = False
    for client in clients:
        try:
            return client.provider.value, _decide(batch, client)
        except _RefusedEverything:
            refused = True
        except (httpx.HTTPError, ValueError):
            logger.warning(
                "Suggested-questions triage failed on %s",
                client.provider,
                exc_info=True,
            )
    # The model would not say whether these excerpts are private, and the
    # rules cannot tell, so keep none of them.
    if refused:
        return "refused", []
    return "rules", [_triage_by_rules(chunk) for chunk in batch]


def _decide(batch: list[InferenceChunk], client: DecisionClient) -> list[TriagedChunk]:
    blocks = [
        f"[{index}] Document: {chunk.semantic_identifier}\n"
        f"{chunk.content[:SQ_TRIAGE_SNIPPET_CHARS]}"
        for index, chunk in enumerate(batch)
    ]
    questions: list[DecisionQuestion] = []
    for index in range(len(batch)):
        questions += [
            ScoreQuestion(
                name=f"usable_{index}",
                instructions=SQ_TRIAGE_USABLE_QUESTION.format(index=index),
                levels=_USABLE_LEVELS,
            ),
            PredicateQuestion(
                name=f"sensitive_{index}",
                instructions=SQ_TRIAGE_SENSITIVE_QUESTION.format(index=index),
            ),
            ChoiceQuestion(
                name=f"topic_{index}",
                instructions=SQ_TRIAGE_TOPIC_QUESTION.format(index=index),
                choices=_TOPIC_CHOICES,
            ),
            PredicateQuestion(
                name=f"fact_{index}",
                instructions=SQ_TRIAGE_FACT_QUESTION.format(index=index),
            ),
        ]
    response = client.decide(
        DecisionRequest(input="\n\n".join(blocks), questions=questions),
        flow=LLMFlow.SUGGESTED_QUESTIONS_TRIAGE,
    )
    if all(isinstance(answer, RefusalAnswer) for answer in response.answers):
        raise _RefusedEverything()
    answers = {answer.name: answer for answer in response.answers}
    return [
        TriagedChunk(
            chunk=chunk,
            usable=_score(answers[f"usable_{index}"]),
            # A refusal on privacy counts as private.
            sensitive=_probability(answers[f"sensitive_{index}"], refused=1.0),
            topic=_topic(answers[f"topic_{index}"]),
            has_fact=_probability(answers[f"fact_{index}"], refused=0.0),
        )
        for index, chunk in enumerate(batch)
    ]


def _score(answer: DecisionAnswer) -> float:
    return answer.score if isinstance(answer, ScoreAnswer) else 0.0


def _probability(answer: DecisionAnswer, refused: float) -> float:
    return answer.probability if isinstance(answer, PredicateAnswer) else refused


def _topic(answer: DecisionAnswer) -> UseCase | None:
    return UseCase(answer.choice) if isinstance(answer, ChoiceAnswer) else None


def _triage_by_rules(chunk: InferenceChunk) -> TriagedChunk:
    useful = chunk.chunk_id <= SQ_RULES_MAX_CHUNK_ID and bool(
        _CONCRETE.search(chunk.content)
    )
    return TriagedChunk(
        chunk=chunk,
        usable=SQ_TRIAGE_MIN_SCORE if useful else 0.0,
        sensitive=1.0 if _SENSITIVE_WORDS.search(chunk.content) else 0.0,
        topic=None,
        has_fact=1.0 if useful else 0.0,
    )


# A question that starts like this is answered by yes or no.
_YES_NO_START = re.compile(
    r"^(am|is|are|was|were|do|does|did|has|have|had|can|could|will|would|"
    r"shall|should|may|might|must|"
    r"isn't|aren't|wasn't|weren't|don't|doesn't|didn't|hasn't|haven't|"
    r"can't|couldn't|won't|wouldn't|shouldn't)\b",
    re.IGNORECASE,
)
_MENTIONS_SOURCE = re.compile(
    r"\b(the document|the passage|this file)\b", re.IGNORECASE
)


def build_writing_llms() -> list[LLM]:
    """OpenAI first, then Anthropic, so an outage or an empty quota at one
    provider does not stop runs. A provider the tenant has not set up, or one
    over its cost limit, is skipped. Fixed in code for the same reason as the
    triage models."""
    llms = []
    for provider, model in (
        (LlmProviderNames.OPENAI, SQ_WRITING_OPENAI_MODEL),
        (LlmProviderNames.ANTHROPIC, SQ_WRITING_ANTHROPIC_MODEL),
    ):
        try:
            llm = get_llm_for_provider(provider, model)
        except (OnyxError, ValueError):
            logger.warning(
                "Suggested questions: cannot use %s for writing",
                provider.value,
                exc_info=True,
            )
            continue
        if llm is not None:
            llms.append(llm)
    return llms


def write_questions(
    passages: list[TriagedChunk],
    llms: list[LLM],
    company: str | None,
    roles: list[str],
) -> list[DraftQuestion]:
    """One call that writes questions about the passages, then drops the ones
    that break the prompt's rules. Tries the LLMs in order; raises when every
    one fails, so the run can retry."""
    passages = passages[:SQ_PASSAGES_MAX]
    if not passages:
        return []
    if not llms:
        raise ValueError("No writing model is set up")
    system_prompt = SQ_WRITING_SYSTEM_PROMPT.format(
        company=company or "the company",
        roles=", ".join(roles) or "any role",
        max_chars=SQ_QUESTION_MAX_CHARS,
        max_questions=SQ_QUESTIONS_PER_RUN,
        per_passage=SQ_QUESTIONS_PER_PASSAGE,
    )
    passages_text = "\n\n".join(
        f"[{number}] {item.chunk.semantic_identifier}\n"
        f"{item.chunk.content[:SQ_PASSAGE_CHARS]}"
        for number, item in enumerate(passages, start=1)
    )
    # OpenAI's JSON mode needs the word "json" in the input messages, and
    # LiteLLM sends the system prompt outside them.
    user_prompt = f"{passages_text}\n\nReturn the questions as JSON."
    for position, llm in enumerate(llms, start=1):
        try:
            written = _write(llm, system_prompt, user_prompt)
        except Exception:
            if position == len(llms):
                raise
            logger.warning(
                "Suggested questions: writing failed on %s, trying the next model",
                llm.config.model_name,
                exc_info=True,
            )
            continue
        drafts = _keep_valid_questions(written, passages)
        logger.info(
            "Suggested questions: %s wrote %d questions from %d passages, kept %d",
            llm.config.model_name,
            len(written),
            len(passages),
            len(drafts),
        )
        return drafts
    return []


def _write(llm: LLM, system_prompt: str, user_prompt: str) -> list[WrittenQuestion]:
    response = llm.invoke(
        GenerationRequest(
            messages=[
                SystemMessage(content=system_prompt),
                UserMessage(content=user_prompt),
            ],
            options=GenerationOptions(
                reasoning_effort=ReasoningEffort.OFF,
                max_tokens=SQ_WRITING_MAX_TOKENS,
                structured_response_format={"type": "json_object"},
            ),
        ),
        context=GenerationContext(
            flow=LLMFlow.SUGGESTED_QUESTIONS, total_timeout_s=SQ_LLM_TIMEOUT_S
        ),
    )
    # Some models wrap the JSON in a code block or add text around it.
    parsed = parse_llm_json_response(response.text)
    if parsed is None:
        raise ValueError("The writing call returned no JSON object")
    return WritingOutput.model_validate(parsed).questions


def _keep_valid_questions(
    written: list[WrittenQuestion], passages: list[TriagedChunk]
) -> list[DraftQuestion]:
    drafts: list[DraftQuestion] = []
    seen: set[str] = set()
    per_passage: Counter[int] = Counter()
    for item in written:
        text = item.question.strip()
        if (
            not 1 <= item.passage <= len(passages)
            or not text.endswith("?")
            or len(text) > SQ_QUESTION_MAX_CHARS
            or _YES_NO_START.match(text)
            or _MENTIONS_SOURCE.search(text)
            or text.lower() in seen
            or per_passage[item.passage] >= SQ_QUESTIONS_PER_PASSAGE
        ):
            continue
        seen.add(text.lower())
        per_passage[item.passage] += 1
        drafts.append(
            DraftQuestion(
                text=text,
                chunk=passages[item.passage - 1].chunk,
                best_for=item.best_for,
            )
        )
        if len(drafts) >= SQ_QUESTIONS_PER_RUN:
            break
    return drafts
