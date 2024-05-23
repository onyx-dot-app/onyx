from collections.abc import Callable

from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.factory import get_default_llm
from danswer.llm.utils import dict_based_prompt_to_langchain_prompt
from danswer.llm.utils import message_to_string
from danswer.prompts.llm_chunk_filter import CHUNK_FILTER_PROMPT
from danswer.prompts.llm_chunk_filter import NONUSEFUL_PAT
from danswer.utils.logger import setup_logger
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def llm_eval_chunk(query: str, chunk_content: str) -> bool:
    def _get_usefulness_messages() -> list[dict[str, str]]:
        messages = [
            {
                "role": "user",
                "content": CHUNK_FILTER_PROMPT.format(
                    chunk_text=chunk_content, user_query=query
                ),
            },
        ]

        return messages

    def _extract_usefulness(model_output: str) -> bool:
        """Default useful if the LLM doesn't match pattern exactly
        This is because it's better to trust the (re)ranking if LLM fails"""
        if model_output.strip().strip('"').lower() == NONUSEFUL_PAT.lower():
            return False
        return True

    # If Gen AI is disabled, none of the messages are more "useful" than any other
    # All are marked not useful (False) so that the icon for Gen AI likes this answer
    # is not shown for any result
    try:
        llm = get_default_llm(use_fast_llm=True, timeout=5)
    except GenAIDisabledException:
        return False

    messages = _get_usefulness_messages()
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    # When running in a batch, it takes as long as the longest thread
    # And when running a large batch, one may fail and take the whole timeout
    # instead cap it to 5 seconds
    model_output = message_to_string(llm.invoke(filled_llm_prompt))
    logger.debug(model_output)

    return _extract_usefulness(model_output)


def llm_batch_eval_chunks(
    query: str, chunk_contents: list[str], use_threads: bool = True
) -> list[bool]:
    if use_threads:
        functions_with_args: list[tuple[Callable, tuple]] = [
            (llm_eval_chunk, (query, chunk_content)) for chunk_content in chunk_contents
        ]

        logger.debug(
            "Running LLM usefulness eval in parallel (following logging may be out of order)"
        )
        parallel_results = run_functions_tuples_in_parallel(
            functions_with_args, allow_failures=True
        )

        # In case of failure/timeout, don't throw out the chunk
        return [True if item is None else item for item in parallel_results]

    else:
        return [
            llm_eval_chunk(query, chunk_content) for chunk_content in chunk_contents
        ]
