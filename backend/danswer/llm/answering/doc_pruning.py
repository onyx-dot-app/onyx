from copy import deepcopy
from typing import TypeVar

from danswer.chat.models import (
    LlmDoc,
)
from danswer.configs.constants import IGNORE_FOR_QA
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.llm.answering.models import DocumentPruningConfig
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.prompts.citations_prompt import compute_max_document_tokens
from danswer.llm.interfaces import LLMConfig
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.llm.utils import tokenizer_trim_content
from danswer.prompts.prompt_utils import build_doc_context_str
from danswer.search.models import InferenceChunk
from danswer.utils.logger import setup_logger


logger = setup_logger()

T = TypeVar("T", bound=LlmDoc | InferenceChunk)

_METADATA_TOKEN_ESTIMATE = 75


class PruningError(Exception):
    pass


def _compute_limit(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    question: str,
    max_chunks: int | None,
    max_window_percentage: float | None,
    max_tokens: int | None,
) -> int:
    llm_max_document_tokens = compute_max_document_tokens(
        prompt_config=prompt_config, llm_config=llm_config, actual_user_input=question
    )

    window_percentage_based_limit = (
        max_window_percentage * llm_max_document_tokens
        if max_window_percentage
        else None
    )
    chunk_count_based_limit = (
        max_chunks * DOC_EMBEDDING_CONTEXT_SIZE if max_chunks else None
    )

    limit_options = [
        lim
        for lim in [
            window_percentage_based_limit,
            chunk_count_based_limit,
            max_tokens,
            llm_max_document_tokens,
        ]
        if lim
    ]
    return int(min(limit_options))


def reorder_docs(
    docs: list[T],
    doc_relevance_list: list[bool] | None,
) -> list[T]:
    if doc_relevance_list is None:
        return docs

    reordered_docs: list[T] = []
    if doc_relevance_list is not None:
        for selection_target in [True, False]:
            for doc, is_relevant in zip(docs, doc_relevance_list):
                if is_relevant == selection_target:
                    reordered_docs.append(doc)
    return reordered_docs


def _remove_docs_to_ignore(docs: list[LlmDoc]) -> list[LlmDoc]:
    return [doc for doc in docs if not doc.metadata.get(IGNORE_FOR_QA)]


def _apply_pruning(
    docs: list[LlmDoc],
    doc_relevance_list: list[bool] | None,
    token_limit: int,
    is_manually_selected_docs: bool,
    use_sections: bool,
) -> list[LlmDoc]:
    llm_tokenizer = get_default_llm_tokenizer()
    docs = deepcopy(docs)  # don't modify in place

    # re-order docs with all the "relevant" docs at the front
    docs = reorder_docs(docs=docs, doc_relevance_list=doc_relevance_list)
    # remove docs that are explicitly marked as not for QA
    docs = _remove_docs_to_ignore(docs=docs)

    tokens_per_doc: list[int] = []
    final_doc_ind = None
    total_tokens = 0
    for ind, llm_doc in enumerate(docs):
        doc_tokens = len(
            llm_tokenizer.encode(
                build_doc_context_str(
                    semantic_identifier=llm_doc.semantic_identifier,
                    source_type=llm_doc.source_type,
                    content=llm_doc.content,
                    metadata_dict=llm_doc.metadata,
                    updated_at=llm_doc.updated_at,
                    ind=ind,
                )
            )
        )
        # if chunks, truncate chunks that are way too long
        # this can happen if the embedding model tokenizer is different
        # than the LLM tokenizer
        if (
            not is_manually_selected_docs
            and not use_sections
            and doc_tokens > DOC_EMBEDDING_CONTEXT_SIZE + _METADATA_TOKEN_ESTIMATE
        ):
            logger.warning(
                "Found more tokens in chunk than expected, "
                "likely mismatch between embedding and LLM tokenizers. Trimming content..."
            )
            llm_doc.content = tokenizer_trim_content(
                content=llm_doc.content,
                desired_length=DOC_EMBEDDING_CONTEXT_SIZE,
                tokenizer=llm_tokenizer,
            )
            doc_tokens = DOC_EMBEDDING_CONTEXT_SIZE
        tokens_per_doc.append(doc_tokens)
        total_tokens += doc_tokens
        if total_tokens > token_limit:
            final_doc_ind = ind
            break

    if final_doc_ind is not None:
        if is_manually_selected_docs or use_sections:
            # for document selection, only allow the final document to get truncated
            # if more than that, then the user message is too long
            if final_doc_ind != len(docs) - 1:
                if use_sections:
                    # Truncate the rest of the list since we're over the token limit
                    # for the last one, trim it. In this case, the Sections can be rather long
                    # so better to trim the back than throw away the whole thing.
                    docs = docs[: final_doc_ind + 1]
                else:
                    raise PruningError(
                        "LLM context window exceeded. Please de-select some documents or shorten your query."
                    )

            final_doc_desired_length = tokens_per_doc[final_doc_ind] - (
                total_tokens - token_limit
            )
            final_doc_content_length = (
                final_doc_desired_length - _METADATA_TOKEN_ESTIMATE
            )
            # this could occur if we only have space for the title / metadata
            # not ideal, but it's the most reasonable thing to do
            # NOTE: the frontend prevents documents from being selected if
            # less than 75 tokens are available to try and avoid this situation
            # from occurring in the first place
            if final_doc_content_length <= 0:
                logger.error(
                    f"Final doc ({docs[final_doc_ind].semantic_identifier}) content "
                    "length is less than 0. Removing this doc from the final prompt."
                )
                docs.pop()
            else:
                docs[final_doc_ind].content = tokenizer_trim_content(
                    content=docs[final_doc_ind].content,
                    desired_length=final_doc_content_length,
                    tokenizer=llm_tokenizer,
                )
        else:
            # For regular search, don't truncate the final document unless it's the only one
            # If it's not the only one, we can throw it away, if it's the only one, we have to truncate
            if final_doc_ind != 0:
                docs = docs[:final_doc_ind]
            else:
                docs[0].content = tokenizer_trim_content(
                    content=docs[0].content,
                    desired_length=token_limit - _METADATA_TOKEN_ESTIMATE,
                    tokenizer=llm_tokenizer,
                )
                docs = [docs[0]]

    return docs


def prune_documents(
    docs: list[LlmDoc],
    doc_relevance_list: list[bool] | None,
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    question: str,
    document_pruning_config: DocumentPruningConfig,
) -> list[LlmDoc]:
    if doc_relevance_list is not None:
        assert len(docs) == len(doc_relevance_list)

    doc_token_limit = _compute_limit(
        prompt_config=prompt_config,
        llm_config=llm_config,
        question=question,
        max_chunks=document_pruning_config.max_chunks,
        max_window_percentage=document_pruning_config.max_window_percentage,
        max_tokens=document_pruning_config.max_tokens,
    )
    return _apply_pruning(
        docs=docs,
        doc_relevance_list=doc_relevance_list,
        token_limit=doc_token_limit,
        is_manually_selected_docs=document_pruning_config.is_manually_selected_docs,
        use_sections=document_pruning_config.use_sections,
    )
