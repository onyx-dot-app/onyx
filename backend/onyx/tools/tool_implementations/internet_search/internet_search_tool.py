import json
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.chat.chat_utils import llm_doc_from_inference_section
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import ContextualPruningConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.citations_prompt import compute_max_document_tokens
from onyx.chat.prompt_builder.citations_prompt import compute_max_llm_input_tokens
from onyx.chat.prune_and_merge import prune_and_merge_sections
from onyx.configs.chat_configs import CONTEXT_CHUNKS_ABOVE
from onyx.configs.chat_configs import CONTEXT_CHUNKS_BELOW
from onyx.configs.chat_configs import NUM_INTERNET_SEARCH_CHUNKS
from onyx.configs.chat_configs import NUM_INTERNET_SEARCH_RESULTS
from onyx.configs.constants import DocumentSource
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.context.search.enums import SearchType
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.db.models import Persona
from onyx.db.search_settings import get_current_search_settings
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.embedder import embed_chunks_with_failure_handling
from onyx.indexing.models import IndexChunk
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.prompts.chat_prompts import INTERNET_SEARCH_QUERY_REPHRASE
from onyx.secondary_llm_flows.choose_search import check_if_need_search
from onyx.secondary_llm_flows.query_expansion import history_based_query_rephrase
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResponseSummary,
)
from onyx.tools.tool_implementations.internet_search.providers import (
    get_default_provider,
)
from onyx.tools.tool_implementations.internet_search.providers import (
    get_provider_by_name,
)
from onyx.tools.tool_implementations.internet_search.providers import (
    InternetSearchProvider,
)
from onyx.tools.tool_implementations.search.search_utils import llm_doc_to_dict
from onyx.tools.tool_implementations.search_like_tool_utils import (
    build_next_prompt_for_search_like_tool,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    documents_to_indexing_documents,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from shared_configs.enums import EmbedTextType

logger = setup_logger()

INTERNET_SEARCH_RESPONSE_SUMMARY_ID = "internet_search_response_summary"
INTERNET_QUERY_FIELD = "internet_search_query"
INTERNET_SEARCH_TOOL_DESCRIPTION = """
This tool searches the internet for current and up-to-date information.
Use this tool when the user asks general knowledge questions that require recent information.

Do not use this tool if:
- The user is asking for information about their work or company.
"""


class InternetSearchTool(Tool[None]):
    _NAME = "run_internet_search"
    _DISPLAY_NAME = "Internet Search"
    _DESCRIPTION = INTERNET_SEARCH_TOOL_DESCRIPTION
    provider: InternetSearchProvider | None

    def __init__(
        self,
        db_session: Session,
        persona: Persona,
        prompt_config: PromptConfig,
        llm: LLM,
        document_pruning_config: DocumentPruningConfig,
        answer_style_config: AnswerStyleConfig,
        provider: str | None = None,
        num_results: int = NUM_INTERNET_SEARCH_RESULTS,
        max_chunks: int = NUM_INTERNET_SEARCH_CHUNKS,
    ) -> None:
        self.db_session = db_session
        self.persona = persona
        self.prompt_config = prompt_config
        self.llm = llm
        self.max_chunks = max_chunks

        self.chunks_above = (
            persona.chunks_above
            if persona.chunks_above is not None
            else CONTEXT_CHUNKS_ABOVE
        )

        self.chunks_below = (
            persona.chunks_below
            if persona.chunks_below is not None
            else CONTEXT_CHUNKS_BELOW
        )

        self.provider = (
            get_provider_by_name(provider) if provider else get_default_provider()
        )

        if not self.provider:
            raise ValueError("No internet search providers are configured")

        self.provider.num_results = num_results

        max_input_tokens = compute_max_llm_input_tokens(
            llm_config=llm.config,
        )
        if max_input_tokens < 3 * GEN_AI_MODEL_FALLBACK_MAX_TOKENS:
            self.chunks_above = 0
            self.chunks_below = 0

        num_chunk_multiple = self.chunks_above + self.chunks_below + 1

        self.answer_style_config = answer_style_config
        self.contextual_pruning_config = (
            ContextualPruningConfig.from_doc_pruning_config(
                num_chunk_multiple=num_chunk_multiple,
                doc_pruning_config=document_pruning_config,
            )
        )

    """For explicit tool calling"""

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        INTERNET_QUERY_FIELD: {
                            "type": "string",
                            "description": "What to search for on the internet",
                        },
                    },
                    "required": [INTERNET_QUERY_FIELD],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        final_context_docs_response = next(
            response for response in args if response.id == FINAL_CONTEXT_DOCUMENTS_ID
        )
        final_context_docs = cast(list[LlmDoc], final_context_docs_response.response)

        return json.dumps(
            {
                "search_results": [
                    llm_doc_to_dict(doc, ind)
                    for ind, doc in enumerate(final_context_docs)
                ]
            }
        )

    """For LLMs that don't support tool calling"""

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        if not force_run and not check_if_need_search(
            query, history, llm, search_type=SearchType.INTERNET
        ):
            return None

        rephrased_query = history_based_query_rephrase(
            query=query,
            history=history,
            llm=llm,
            prompt_template=INTERNET_SEARCH_QUERY_REPHRASE,
        )
        return {
            INTERNET_QUERY_FIELD: rephrased_query,
        }

    def _perform_search(self, query: str, token_budget: int) -> list[Document]:
        if not self.provider:
            raise RuntimeError("Internet search provider is not configured")

        logger.info(
            f"Performing internet search with {self.provider.name} provider: {query}"
        )

        results = self.provider.search(query, token_budget)

        results_as_documents = []

        for result in results:
            document = Document(
                id="INTERNET_SEARCH_DOC_" + result.link,
                semantic_identifier=result.title,
                source=DocumentSource.WEB,
                doc_updated_at=(
                    result.published_date
                    if result.published_date
                    else datetime.now(timezone.utc)
                ),
                sections=[
                    TextSection(
                        link=result.link,
                        text=result.full_content,
                    )
                ],
                metadata={},
            )
            results_as_documents.append(document)

        return results_as_documents

    def _chunk_and_embed_results(
        self, results: list[Document], embedding_model: DefaultIndexingEmbedder
    ) -> list[IndexChunk]:
        chunker = Chunker(
            tokenizer=embedding_model.embedding_model.tokenizer,
        )
        prepped_results = documents_to_indexing_documents(results)

        chunks = chunker.chunk(prepped_results)

        chunks_with_embeddings, _ = (
            embed_chunks_with_failure_handling(chunks=chunks, embedder=embedding_model)
            if chunks
            else ([], [])
        )

        return chunks_with_embeddings

    def _calculate_cosine_similarity_scores(
        self, query_embedding: list[float], chunks: list[IndexChunk]
    ) -> dict[str, float]:
        """Calculate cosine similarity scores for chunks and return as a mapping"""

        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        # Create a mapping of chunk ID to similarity score
        chunk_scores = {}
        for chunk in chunks:
            chunk_key = f"{chunk.source_document.id}_{chunk.chunk_id}"
            chunk_scores[chunk_key] = cosine_similarity(
                query_embedding, chunk.embeddings.full_embedding
            )

        return chunk_scores

    def _create_inference_chunk_from_index_chunk(
        self, chunk: IndexChunk, similarity_score: float
    ) -> InferenceChunk:
        source_link = chunk.get_link()
        source_links = {0: source_link} if source_link else {}

        return InferenceChunk(
            chunk_id=chunk.chunk_id,
            blurb=chunk.blurb,
            content=chunk.content,
            source_links=source_links,
            section_continuation=chunk.section_continuation,
            document_id=chunk.source_document.id,
            source_type=chunk.source_document.source,
            semantic_identifier=chunk.source_document.semantic_identifier,
            title=chunk.source_document.title,
            boost=1,
            recency_bias=1.0,
            score=similarity_score,
            hidden=False,
            metadata=chunk.source_document.metadata,
            match_highlights=[],
            doc_summary=chunk.doc_summary,
            chunk_context=chunk.chunk_context,
            updated_at=chunk.source_document.doc_updated_at,
            image_file_id=None,
        )

    def _convert_chunks_into_sections(
        self, chunks: list[IndexChunk], similarity_scores: dict[str, float]
    ) -> list[InferenceSection]:
        inference_chunks: list[InferenceChunk] = []

        # Convert IndexChunk to InferenceChunk
        for index_chunk in chunks:

            chunk_key = f"{index_chunk.source_document.id}_{index_chunk.chunk_id}"
            score = similarity_scores.get(chunk_key, 0.0)

            inference_chunk = self._create_inference_chunk_from_index_chunk(
                index_chunk, score
            )
            inference_chunks.append(inference_chunk)

        # Limit to max_chunks results to process
        sorted_inference_chunks = sorted(
            inference_chunks, key=lambda x: x.score or 0, reverse=True
        )
        sorted_inference_chunks = sorted_inference_chunks[: self.max_chunks]

        # NOTE: chunks_above and chunks_below are set to 0
        # If we ever decide to use them, we need to add that logic to the inference section
        # Section merging/pruning happens after this in run()
        sections: list[InferenceSection] = []
        for inference_chunk in sorted_inference_chunks:
            new_section = InferenceSection(
                center_chunk=inference_chunk,
                chunks=[inference_chunk],
                combined_content=inference_chunk.content,
            )
            sections.append(new_section)

        return sections

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        search_settings = get_current_search_settings(db_session=self.db_session)
        embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
            search_settings=search_settings
        )

        query = cast(str, llm_kwargs[INTERNET_QUERY_FIELD])
        query_embedding = embedding_model.embedding_model.encode(
            [query], text_type=EmbedTextType.QUERY
        )[0]

        token_budget = compute_max_document_tokens(
            prompt_config=self.prompt_config,
            llm_config=self.llm.config,
            actual_user_input=query,
            tool_token_count=self.contextual_pruning_config.tool_num_tokens,
        )

        # Token budget can be used with search APIs that return LLM context strings
        search_results = self._perform_search(query, token_budget)
        chunks_with_embeddings = self._chunk_and_embed_results(
            search_results, embedding_model
        )
        similarity_scores = self._calculate_cosine_similarity_scores(
            query_embedding, chunks_with_embeddings
        )
        sections = self._convert_chunks_into_sections(
            chunks_with_embeddings, similarity_scores
        )

        if sections:
            pruned_sections = prune_and_merge_sections(
                sections=sections,
                section_relevance_list=None,  # All results are considered relevant
                prompt_config=self.prompt_config,
                llm_config=self.llm.config,
                question=query,
                contextual_pruning_config=self.contextual_pruning_config,
            )
        else:
            pruned_sections = sections

        yield ToolResponse(
            id=INTERNET_SEARCH_RESPONSE_SUMMARY_ID,
            response=InternetSearchResponseSummary(
                query=query,
                top_sections=pruned_sections,
            ),
        )

        llm_docs = [
            llm_doc_from_inference_section(section) for section in pruned_sections
        ]

        yield ToolResponse(id=FINAL_CONTEXT_DOCUMENTS_ID, response=llm_docs)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Extract the final context documents from tool responses"""
        final_docs = cast(
            list[LlmDoc],
            next(arg.response for arg in args if arg.id == FINAL_CONTEXT_DOCUMENTS_ID),
        )
        return [json.loads(doc.model_dump_json()) for doc in final_docs]

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        """Build the next prompt for the LLM using the search results"""
        return build_next_prompt_for_search_like_tool(
            prompt_builder=prompt_builder,
            tool_call_summary=tool_call_summary,
            tool_responses=tool_responses,
            using_tool_calling_llm=using_tool_calling_llm,
            answer_style_config=self.answer_style_config,
            prompt_config=self.prompt_config,
            context_type="internet search results",
        )
