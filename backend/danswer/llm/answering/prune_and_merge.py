import json
from collections import defaultdict
from copy import deepcopy
from typing import TypeVar

from pydantic import BaseModel

from danswer.chat.models import (
    LlmDoc,
)
from danswer.configs.constants import IGNORE_FOR_QA
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.llm.answering.models import ContextualPruningConfig
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.prompts.citations_prompt import compute_max_document_tokens
from danswer.llm.interfaces import LLMConfig
from danswer.natural_language_processing.utils import get_tokenizer
from danswer.natural_language_processing.utils import tokenizer_trim_content
from danswer.prompts.prompt_utils import build_doc_context_str
from danswer.search.models import InferenceChunk
from danswer.search.models import InferenceSection
from danswer.tools.search.search_utils import section_to_dict
from danswer.utils.logger import setup_logger


logger = setup_logger()

T = TypeVar("T", bound=LlmDoc | InferenceChunk | InferenceSection)

_METADATA_TOKEN_ESTIMATE = 75
# Title and additional tokens as part of the tool message json
# this is only used to log a warning so we can be more forgiving with the buffer
_OVERCOUNT_ESTIMATE = 256


class PruningError(Exception):
    pass


class ChunkRange(BaseModel):
    chunks: list[InferenceChunk]
    start: int
    end: int


def merge_chunk_intervals(chunk_ranges: list[ChunkRange]) -> list[ChunkRange]:
    """
    This acts on a single document to merge the overlapping ranges of chunks
    Algo explained here for easy understanding: https://leetcode.com/problems/merge-intervals

    NOTE: this is used to merge chunk ranges for retrieving the right chunk_ids against the
    document index, this does not merge the actual contents so it should not be used to actually
    merge chunks post retrieval.
    """
    sorted_ranges = sorted(chunk_ranges, key=lambda x: x.start)

    combined_ranges: list[ChunkRange] = []

    for new_chunk_range in sorted_ranges:
        if not combined_ranges or combined_ranges[-1].end < new_chunk_range.start - 1:
            combined_ranges.append(new_chunk_range)
        else:
            current_range = combined_ranges[-1]
            current_range.end = max(current_range.end, new_chunk_range.end)
            current_range.chunks.extend(new_chunk_range.chunks)

    return combined_ranges


def _compute_limit(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    question: str,
    max_chunks: int | None,
    max_window_percentage: float | None,
    max_tokens: int | None,
    tool_token_count: int,
) -> int:
    llm_max_document_tokens = compute_max_document_tokens(
        prompt_config=prompt_config,
        llm_config=llm_config,
        tool_token_count=tool_token_count,
        actual_user_input=question,
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


def reorder_sections(
    sections: list[InferenceSection],
    section_relevance_list: list[bool] | None,
) -> list[InferenceSection]:
    if section_relevance_list is None:
        return sections

    reordered_sections: list[InferenceSection] = []
    if section_relevance_list is not None:
        for selection_target in [True, False]:
            for section, is_relevant in zip(sections, section_relevance_list):
                if is_relevant == selection_target:
                    reordered_sections.append(section)
    return reordered_sections


def _remove_sections_to_ignore(
    sections: list[InferenceSection],
) -> list[InferenceSection]:
    return [
        section
        for section in sections
        if not section.center_chunk.metadata.get(IGNORE_FOR_QA)
    ]


def _apply_pruning(
    sections: list[InferenceSection],
    section_relevance_list: list[bool] | None,
    token_limit: int,
    is_manually_selected_docs: bool,
    use_sections: bool,
    using_tool_message: bool,
    llm_config: LLMConfig,
) -> list[InferenceSection]:
    llm_tokenizer = get_tokenizer(
        provider_type=llm_config.model_provider,
        model_name=llm_config.model_name,
    )
    sections = deepcopy(sections)  # don't modify in place

    # re-order docs with all the "relevant" docs at the front
    sections = reorder_sections(
        sections=sections, section_relevance_list=section_relevance_list
    )
    # remove docs that are explicitly marked as not for QA
    sections = _remove_sections_to_ignore(sections=sections)

    final_section_ind = None
    total_tokens = 0
    for ind, section in enumerate(sections):
        section_str = (
            # If using tool message, it will be a bit of an overestimate as the extra json text around the section
            # will be counted towards the token count. However, once the Sections are merged, the extra json parts
            # that overlap will not be counted multiple times like it is in the pruning step.
            json.dumps(section_to_dict(section, ind))
            if using_tool_message
            else build_doc_context_str(
                semantic_identifier=section.center_chunk.semantic_identifier,
                source_type=section.center_chunk.source_type,
                content=section.combined_content,
                metadata_dict=section.center_chunk.metadata,
                updated_at=section.center_chunk.updated_at,
                ind=ind,
            )
        )

        section_token_count = len(llm_tokenizer.encode(section_str))
        # if not using sections (specifically, using Sections where each section maps exactly to the one center chunk),
        # truncate chunks that are way too long. This can happen if the embedding model tokenizer is different
        # than the LLM tokenizer
        if (
            not is_manually_selected_docs
            and not use_sections
            and section_token_count
            > DOC_EMBEDDING_CONTEXT_SIZE + _METADATA_TOKEN_ESTIMATE
        ):
            if (
                section_token_count
                > DOC_EMBEDDING_CONTEXT_SIZE
                + _METADATA_TOKEN_ESTIMATE
                + _OVERCOUNT_ESTIMATE
            ):
                # If the section is just a little bit over, it is likely due to the additional tool message tokens
                # no need to record this, the content will be trimmed just in case
                logger.warning(
                    "Found more tokens in Section than expected, "
                    "likely mismatch between embedding and LLM tokenizers. Trimming content..."
                )
            section.combined_content = tokenizer_trim_content(
                content=section.combined_content,
                desired_length=DOC_EMBEDDING_CONTEXT_SIZE,
                tokenizer=llm_tokenizer,
            )
            section_token_count = DOC_EMBEDDING_CONTEXT_SIZE

        total_tokens += section_token_count
        if total_tokens > token_limit:
            final_section_ind = ind
            break

    if final_section_ind is not None:
        if is_manually_selected_docs or use_sections:
            if final_section_ind != len(sections) - 1:
                # If using Sections, then the final section could be more than we need, in this case we are willing to
                # truncate the final section to fit the specified context window
                sections = sections[: final_section_ind + 1]

                if is_manually_selected_docs:
                    # For document selection flow, only allow the final document/section to get truncated
                    # if more than that needs to be throw away then some documents are completely thrown away in which
                    # case this should be reported to the user as an error
                    raise PruningError(
                        "LLM context window exceeded. Please de-select some documents or shorten your query."
                    )

            amount_to_truncate = total_tokens - token_limit
            # NOTE: need to recalculate the length here, since the previous calculation included
            # overhead from JSON-fying the doc / the metadata
            final_doc_content_length = len(
                llm_tokenizer.encode(sections[final_section_ind].combined_content)
            ) - (amount_to_truncate)
            # this could occur if we only have space for the title / metadata
            # not ideal, but it's the most reasonable thing to do
            # NOTE: the frontend prevents documents from being selected if
            # less than 75 tokens are available to try and avoid this situation
            # from occurring in the first place
            if final_doc_content_length <= 0:
                logger.error(
                    f"Final section ({sections[final_section_ind].center_chunk.semantic_identifier}) content "
                    "length is less than 0. Removing this section from the final prompt."
                )
                sections.pop()
            else:
                sections[final_section_ind].combined_content = tokenizer_trim_content(
                    content=sections[final_section_ind].combined_content,
                    desired_length=final_doc_content_length,
                    tokenizer=llm_tokenizer,
                )
        else:
            # For search on chunk level (Section is just a chunk), don't truncate the final Chunk/Section unless it's the only one
            # If it's not the only one, we can throw it away, if it's the only one, we have to truncate
            if final_section_ind != 0:
                sections = sections[:final_section_ind]
            else:
                sections[0].combined_content = tokenizer_trim_content(
                    content=sections[0].combined_content,
                    desired_length=token_limit - _METADATA_TOKEN_ESTIMATE,
                    tokenizer=llm_tokenizer,
                )
                sections = [sections[0]]

    return sections


def prune_sections(
    sections: list[InferenceSection],
    section_relevance_list: list[bool] | None,
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    question: str,
    contextual_pruning_config: ContextualPruningConfig,
) -> list[InferenceSection]:
    # Assumes the sections are score ordered with highest first
    if section_relevance_list is not None:
        assert len(sections) == len(section_relevance_list)

    actual_num_chunks = (
        contextual_pruning_config.max_chunks
        * contextual_pruning_config.num_chunk_multiple
        if contextual_pruning_config.max_chunks
        else None
    )

    token_limit = _compute_limit(
        prompt_config=prompt_config,
        llm_config=llm_config,
        question=question,
        max_chunks=actual_num_chunks,
        max_window_percentage=contextual_pruning_config.max_window_percentage,
        max_tokens=contextual_pruning_config.max_tokens,
        tool_token_count=contextual_pruning_config.tool_num_tokens,
    )

    return _apply_pruning(
        sections=sections,
        section_relevance_list=section_relevance_list,
        token_limit=token_limit,
        is_manually_selected_docs=contextual_pruning_config.is_manually_selected_docs,
        use_sections=contextual_pruning_config.use_sections,  # Now default True
        using_tool_message=contextual_pruning_config.using_tool_message,
        llm_config=llm_config,
    )


def _merge_doc_chunks(chunks: list[InferenceChunk]) -> InferenceSection:
    # Assuming there are no duplicates by this point
    sorted_chunks = sorted(chunks, key=lambda x: x.chunk_id)

    center_chunk = max(
        chunks, key=lambda x: x.score if x.score is not None else float("-inf")
    )

    merged_content = []
    for i, chunk in enumerate(sorted_chunks):
        if i > 0:
            prev_chunk_id = sorted_chunks[i - 1].chunk_id
            if chunk.chunk_id == prev_chunk_id + 1:
                merged_content.append("\n")
            else:
                merged_content.append("\n\n...\n\n")
        merged_content.append(chunk.content)

    combined_content = "".join(merged_content)

    return InferenceSection(
        center_chunk=center_chunk,
        chunks=sorted_chunks,
        combined_content=combined_content,
    )


def _merge_sections(sections: list[InferenceSection]) -> list[InferenceSection]:
    docs_map: dict[str, dict[int, InferenceChunk]] = defaultdict(dict)
    doc_order: dict[str, int] = {}
    for index, section in enumerate(sections):
        if section.center_chunk.document_id not in doc_order:
            doc_order[section.center_chunk.document_id] = index
        for chunk in [section.center_chunk] + section.chunks:
            chunks_map = docs_map[section.center_chunk.document_id]
            existing_chunk = chunks_map.get(chunk.chunk_id)
            if (
                existing_chunk is None
                or existing_chunk.score is None
                or chunk.score is not None
                and chunk.score > existing_chunk.score
            ):
                chunks_map[chunk.chunk_id] = chunk

    new_sections = []
    for section_chunks in docs_map.values():
        new_sections.append(_merge_doc_chunks(chunks=list(section_chunks.values())))

    # Sort by highest score, then by original document order
    # It is now 1 large section per doc, the center chunk being the one with the highest score
    new_sections.sort(
        key=lambda x: (
            x.center_chunk.score if x.center_chunk.score is not None else 0,
            -1 * doc_order[x.center_chunk.document_id],
        ),
        reverse=True,
    )

    return new_sections


def prune_and_merge_sections(
    sections: list[InferenceSection],
    section_relevance_list: list[bool] | None,
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    question: str,
    contextual_pruning_config: ContextualPruningConfig,
) -> list[InferenceSection]:
    # Assumes the sections are score ordered with highest first
    remaining_sections = prune_sections(
        sections=sections,
        section_relevance_list=section_relevance_list,
        prompt_config=prompt_config,
        llm_config=llm_config,
        question=question,
        contextual_pruning_config=contextual_pruning_config,
    )

    merged_sections = _merge_sections(sections=remaining_sections)

    return merged_sections
