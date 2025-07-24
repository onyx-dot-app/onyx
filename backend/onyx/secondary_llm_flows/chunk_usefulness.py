from collections.abc import Callable

from onyx.configs.chat_configs import DISABLE_LLM_DOC_RELEVANCE
from onyx.llm.interfaces import LLM
from onyx.llm.utils import dict_based_prompt_to_langchain_prompt
from onyx.llm.utils import message_to_string
from onyx.prompts.llm_chunk_filter import NONUSEFUL_PAT
from onyx.prompts.llm_chunk_filter import SECTION_FILTER_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


def llm_eval_section(
    query: str,
    section_content: str,
    llm: LLM,
    title: str,
    metadata: dict[str, str | list[str]],
) -> bool:
    def _get_metadata_str(metadata: dict[str, str | list[str]]) -> str:
        metadata_str = "\nMetadata:\n"
        for key, value in metadata.items():
            value_str = ", ".join(value) if isinstance(value, list) else value
            metadata_str += f"{key} - {value_str}\n"
        return metadata_str

    def _get_usefulness_messages() -> list[dict[str, str]]:
        metadata_str = _get_metadata_str(metadata) if metadata else ""
        messages = [
            {
                "role": "user",
                "content": SECTION_FILTER_PROMPT.format(
                    title=title.replace("\n", " "),
                    chunk_text=section_content,
                    user_query=query,
                    optional_metadata=metadata_str,
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

    messages = _get_usefulness_messages()
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    model_output = message_to_string(llm.invoke(filled_llm_prompt))

    # NOTE(rkuo): all this does is print "Yes useful" or "Not useful"
    # disabling becuase it's spammy, restore and give more context if this is needed
    # logger.debug(model_output)

    return _extract_usefulness(model_output)


def llm_batch_eval_sections(
    query: str,
    section_contents: list[str],
    llm: LLM,
    titles: list[str],
    metadata_list: list[dict[str, str | list[str]]],
    use_threads: bool = True,
) -> list[bool]:
    answer: list[bool]

    if DISABLE_LLM_DOC_RELEVANCE:
        raise RuntimeError(
            "LLM Doc Relevance is globally disabled, "
            "this should have been caught upstream."
        )

    if use_threads:
        functions_with_args: list[tuple[Callable, tuple]] = [
            (llm_eval_section, (query, section_content, llm, title, metadata))
            for section_content, title, metadata in zip(
                section_contents, titles, metadata_list
            )
        ]

        logger.debug(
            "Running LLM usefulness eval in parallel (following logging may be out of order)"
        )
        parallel_results = run_functions_tuples_in_parallel(
            functions_with_args, allow_failures=True
        )

        # In case of failure/timeout, don't throw out the section
        answer = [True if item is None else item for item in parallel_results]
        return answer

    answer = [
        llm_eval_section(query, section_content, llm, title, metadata)
        for section_content, title, metadata in zip(
            section_contents, titles, metadata_list
        )
    ]
    return answer
