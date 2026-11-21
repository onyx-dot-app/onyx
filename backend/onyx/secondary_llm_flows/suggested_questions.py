"""The writing calls for suggested questions. A small model reads the
passages, skips the ones with nothing to ask about or with private
information, and writes questions about the rest. It thinks a little first:
without thinking it wrote questions from private passages. The passages are
split by document into a few calls that run at the same time, so a run takes
as long as one short call."""

import logging
import re

from onyx.context.search.models import InferenceChunk
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import get_llm_for_provider
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    ReasoningEffort,
    SystemMessage,
    UserMessage,
)
from onyx.prompts.suggested_questions import SQ_WRITING_SYSTEM_PROMPT
from onyx.server.features.suggested_questions.config import (
    SQ_LLM_TIMEOUT_S,
    SQ_PASSAGE_CHARS,
    SQ_PASSAGES_MAX,
    SQ_QUESTION_MAX_CHARS,
    SQ_QUESTIONS_PER_RUN,
    SQ_WRITING_ANTHROPIC_MODEL,
    SQ_WRITING_CALLS,
    SQ_WRITING_MAX_TOKENS,
    SQ_WRITING_OPENAI_MODEL,
)
from onyx.server.features.suggested_questions.models import (
    DraftQuestion,
    WritingOutput,
    WrittenQuestion,
)
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import parse_llm_json_response
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

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
    over its cost limit, is skipped.

    The models are fixed in code because this runs only on the Playground,
    where we set up every tenant's providers. Before it runs for other
    deployments, try the admin's default model first: their setup may have no
    OpenAI or Anthropic provider."""
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
    chunks: list[InferenceChunk],
    llms: list[LLM],
    company: str | None,
    roles: list[str],
) -> list[DraftQuestion]:
    """Questions about the first SQ_PASSAGES_MAX chunks, at most one per
    document. The documents are dealt out in turn to up to SQ_WRITING_CALLS
    calls that run at the same time, so every call gets a mix and a
    document's passages stay together. A call that fails on every LLM only
    loses its own questions; raises when every call fails, so the run can
    retry."""
    passages = chunks[:SQ_PASSAGES_MAX]
    if not passages:
        return []
    if not llms:
        raise ValueError("No writing model is set up")
    documents = list(dict.fromkeys(chunk.document_id for chunk in passages))
    calls = min(SQ_WRITING_CALLS, len(documents))
    groups = [set(documents[start::calls]) for start in range(calls)]
    # Rounded up, so the calls together can fill the run.
    per_call = -(-SQ_QUESTIONS_PER_RUN // calls)
    system_prompt = SQ_WRITING_SYSTEM_PROMPT.format(
        company=company or "the company",
        roles=", ".join(roles) or "any role",
        max_chars=SQ_QUESTION_MAX_CHARS,
        max_questions=per_call,
    )
    results: list[tuple[int, list[DraftQuestion]] | None] = (
        run_functions_tuples_in_parallel(
            [
                (
                    _write_call,
                    (
                        [chunk for chunk in passages if chunk.document_id in group],
                        llms,
                        system_prompt,
                        per_call,
                    ),
                )
                for group in groups
            ]
        )
    )
    done = [result for result in results if result is not None]
    if not done:
        raise RuntimeError(f"Every one of {calls} writing calls failed")
    drafts: list[DraftQuestion] = []
    seen: set[str] = set()
    for _, call_drafts in done:
        for draft in call_drafts:
            if draft.text.lower() not in seen:
                seen.add(draft.text.lower())
                drafts.append(draft)
    drafts = drafts[:SQ_QUESTIONS_PER_RUN]
    logger.log(
        logging.WARNING if len(done) < calls else logging.INFO,
        "Suggested questions: %d of %d writing calls wrote %d questions from %d "
        "passages, kept %d",
        len(done),
        calls,
        sum(written for written, _ in done),
        len(passages),
        len(drafts),
    )
    return drafts


def _write_call(
    passages: list[InferenceChunk], llms: list[LLM], system_prompt: str, limit: int
) -> tuple[int, list[DraftQuestion]] | None:
    """One call's questions and how many it wrote before the checks. Tries
    the LLMs in order; None when every one fails."""
    passages_text = "\n\n".join(
        f"[{number}] {chunk.semantic_identifier}\n{chunk.content[:SQ_PASSAGE_CHARS]}"
        for number, chunk in enumerate(passages, start=1)
    )
    # OpenAI's JSON mode needs the word "json" in the input messages, and
    # LiteLLM sends the system prompt outside them.
    user_prompt = f"{passages_text}\n\nReturn the questions as JSON."
    for position, llm in enumerate(llms, start=1):
        try:
            written = _write(llm, system_prompt, user_prompt)
        except Exception:
            logger.warning(
                "Suggested questions: writing failed on %s%s",
                llm.config.model_name,
                ", trying the next model" if position < len(llms) else "",
                exc_info=True,
            )
            continue
        return len(written), _keep_valid_questions(written, passages, limit)
    return None


def _write(llm: LLM, system_prompt: str, user_prompt: str) -> list[WrittenQuestion]:
    response = llm.invoke(
        GenerationRequest(
            messages=[
                SystemMessage(content=system_prompt),
                UserMessage(content=user_prompt),
            ],
            options=GenerationOptions(
                reasoning_effort=ReasoningEffort.LOW,
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
    written: list[WrittenQuestion], passages: list[InferenceChunk], limit: int
) -> list[DraftQuestion]:
    """Up to `limit` questions that follow the rules, one per document: a
    shelf keeps only one question per document, so a second one would be
    lost."""
    drafts: list[DraftQuestion] = []
    seen: set[str] = set()
    documents: set[str] = set()
    for item in written:
        text = item.question.strip()
        if (
            not 1 <= item.passage <= len(passages)
            or not text.endswith("?")
            or len(text) > SQ_QUESTION_MAX_CHARS
            or _YES_NO_START.match(text)
            or _MENTIONS_SOURCE.search(text)
            or text.lower() in seen
        ):
            continue
        chunk = passages[item.passage - 1]
        if chunk.document_id in documents:
            continue
        seen.add(text.lower())
        documents.add(chunk.document_id)
        drafts.append(DraftQuestion(text=text, chunk=chunk, best_for=item.best_for))
        if len(drafts) >= limit:
            break
    return drafts
