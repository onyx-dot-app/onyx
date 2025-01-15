# NOTE No longer used. This needs to be revisited later.
import re
from collections.abc import Iterator

from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import StreamingError
from onyx.llm.exceptions import GenAIDisabledException
from onyx.llm.factory import get_default_llms
from onyx.llm.utils import dict_based_prompt_to_langchain_prompt
from onyx.llm.utils import message_generator_to_string_generator
from onyx.llm.utils import message_to_string
from onyx.prompts.constants import ANSWERABLE_PAT
from onyx.prompts.constants import THOUGHT_PAT
from onyx.prompts.query_validation import ANSWERABLE_PROMPT
from onyx.server.query_and_chat.models import QueryValidationResponse
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_query_validation_messages(user_query: str) -> list[dict[str, str]]:
    messages = [
        {
            "role": "user",
            "content": ANSWERABLE_PROMPT.format(user_query=user_query),
        },
    ]

    return messages


def extract_answerability_reasoning(model_raw: str) -> str:
    reasoning_match = re.search(
        f"{THOUGHT_PAT.upper()}(.*?){ANSWERABLE_PAT.upper()}", model_raw, re.DOTALL
    )
    reasoning_text = reasoning_match.group(1).strip() if reasoning_match else ""
    return reasoning_text


def extract_answerability_bool(model_raw: str) -> bool:
    answerable_match = re.search(f"{ANSWERABLE_PAT.upper()}(.+)", model_raw)
    answerable_text = answerable_match.group(1).strip() if answerable_match else ""
    answerable = True if answerable_text.strip().lower() in ["true", "yes"] else False
    return answerable


def get_query_answerability(
    user_query: str, skip_check: bool = False
) -> tuple[str, bool]:
    if skip_check:
        return "Query Answerability Evaluation feature is turned off", True

    try:
        llm, _ = get_default_llms()
    except GenAIDisabledException:
        return "Generative AI is turned off - skipping check", True

    messages = get_query_validation_messages(user_query)
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    model_output = message_to_string(llm.invoke(filled_llm_prompt))

    reasoning = extract_answerability_reasoning(model_output)
    answerable = extract_answerability_bool(model_output)

    return reasoning, answerable


def stream_query_answerability(
    user_query: str, skip_check: bool = False
) -> Iterator[str]:
    if skip_check:
        yield get_json_line(
            QueryValidationResponse(
                reasoning="Query Answerability Evaluation feature is turned off",
                answerable=True,
            ).model_dump()
        )
        return

    try:
        llm, _ = get_default_llms()
    except GenAIDisabledException:
        yield get_json_line(
            QueryValidationResponse(
                reasoning="Generative AI is turned off - skipping check",
                answerable=True,
            ).model_dump()
        )
        return
    messages = get_query_validation_messages(user_query)
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    try:
        tokens = message_generator_to_string_generator(llm.stream(filled_llm_prompt))
        reasoning_pat_found = False
        model_output = ""
        hold_answerable = ""
        for token in tokens:
            model_output = model_output + token

            if ANSWERABLE_PAT.upper() in model_output:
                continue

            if not reasoning_pat_found and THOUGHT_PAT.upper() in model_output:
                reasoning_pat_found = True
                reason_ind = model_output.find(THOUGHT_PAT.upper())
                remaining = model_output[reason_ind + len(THOUGHT_PAT.upper()) :]
                if remaining:
                    yield get_json_line(
                        OnyxAnswerPiece(answer_piece=remaining).model_dump()
                    )
                continue

            if reasoning_pat_found:
                hold_answerable = hold_answerable + token
                if hold_answerable == ANSWERABLE_PAT.upper()[: len(hold_answerable)]:
                    continue
                yield get_json_line(
                    OnyxAnswerPiece(answer_piece=hold_answerable).model_dump()
                )
                hold_answerable = ""

        reasoning = extract_answerability_reasoning(model_output)
        answerable = extract_answerability_bool(model_output)

        yield get_json_line(
            QueryValidationResponse(
                reasoning=reasoning, answerable=answerable
            ).model_dump()
        )
    except Exception as e:
        # exception is logged in the answer_question method, no need to re-log
        error = StreamingError(error=str(e))
        yield get_json_line(error.model_dump())
        logger.exception("Failed to validate Query")
    return
