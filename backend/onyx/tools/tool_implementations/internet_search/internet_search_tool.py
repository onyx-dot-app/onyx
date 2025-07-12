import json
from collections.abc import Generator
from datetime import datetime
from typing import Any
from typing import cast

import httpx
from sqlalchemy.orm import Session

from onyx.chat.chat_utils import combine_message_chain
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.citations_prompt import compute_max_llm_input_tokens
from onyx.configs.constants import DocumentSource
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.search_settings import get_current_search_settings
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.embedder import embed_chunks_with_failure_handling
from onyx.indexing.indexing_pipeline import process_image_sections
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import message_to_string
from onyx.prompts.chat_prompts import INTERNET_SEARCH_QUERY_REPHRASE
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.secondary_llm_flows.query_expansion import history_based_query_rephrase
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResponse,
)
from onyx.tools.tool_implementations.internet_search.models import InternetSearchResult
from onyx.tools.tool_implementations.internet_search.utils import (
    internet_search_chunk_to_llm_doc,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    build_next_prompt_for_search_like_tool,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from shared_configs.enums import EmbedTextType

logger = setup_logger()

INTERNET_SEARCH_RESPONSE_ID = "internet_search_response"

YES_INTERNET_SEARCH = "Yes Internet Search"
SKIP_INTERNET_SEARCH = "Skip Internet Search"

INTERNET_SEARCH_TEMPLATE = f"""
Given the conversation history and a follow up query, determine if the system should call \
an external internet search tool to better answer the latest user input.
Your default response is {SKIP_INTERNET_SEARCH}.

Respond "{YES_INTERNET_SEARCH}" if:
- The user is asking for information that requires an internet search.

Conversation History:
{GENERAL_SEP_PAT}
{{chat_history}}
{GENERAL_SEP_PAT}

If you are at all unsure, respond with {SKIP_INTERNET_SEARCH}.
Respond with EXACTLY and ONLY "{YES_INTERNET_SEARCH}" or "{SKIP_INTERNET_SEARCH}"

Follow Up Input:
{{final_query}}
""".strip()


# override_kwargs is not supported for internet search tools
class InternetSearchTool(Tool[None]):
    _NAME = "run_internet_search"
    _DISPLAY_NAME = "Internet Search"
    _DESCRIPTION = "Perform an internet search for up-to-date information."

    # TODO: Tool constructor sets answerstyle to all sources relevant, but that is not true for internet search
    def __init__(
        self,
        db_session: Session,
        llm: LLM,
        api_key: str,
        pruning_config: DocumentPruningConfig,
        answer_style_config: AnswerStyleConfig,
        prompt_config: PromptConfig,
        num_results: int = 10,
    ) -> None:
        self.db_session = db_session
        self.llm = llm
        self.api_key = api_key
        self.pruning_config = pruning_config
        self.answer_style_config = answer_style_config
        self.prompt_config = prompt_config

        self.host = "https://api.exa.ai"
        self.headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }
        self.num_results = num_results

        max_input_tokens = compute_max_llm_input_tokens(
            llm_config=llm.config,
        )
        if max_input_tokens < 3 * GEN_AI_MODEL_FALLBACK_MAX_TOKENS:
            self.chunks_above = 0
            self.chunks_below = 0

        self.chunks_above + self.chunks_below + 1

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
                        "internet_search_query": {
                            "type": "string",
                            "description": "Query to search on the internet",
                        },
                    },
                    "required": ["internet_search_query"],
                },
            },
        }

    """For LLMs that don't support tool calling"""

    def check_if_needs_internet_search(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
    ) -> bool:
        history_str = combine_message_chain(
            messages=history, token_limit=GEN_AI_HISTORY_CUTOFF
        )
        prompt = INTERNET_SEARCH_TEMPLATE.format(
            chat_history=history_str,
            final_query=query,
        )
        use_internet_search_output = message_to_string(llm.invoke(prompt))

        logger.debug(
            f"Evaluated if should use internet search: {use_internet_search_output}"
        )

        return (
            YES_INTERNET_SEARCH.split()[0]
        ).lower() in use_internet_search_output.lower()

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        if not force_run and not self.check_if_needs_internet_search(
            query, history, llm
        ):
            return None

        rephrased_query = history_based_query_rephrase(
            query=query,
            history=history,
            llm=llm,
            prompt_template=INTERNET_SEARCH_QUERY_REPHRASE,
        )
        return {
            "internet_search_query": rephrased_query,
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        search_response = cast(InternetSearchResponse, args[0].response)
        return json.dumps(search_response.model_dump(), default=str)

    def _perform_search(self, query: str) -> InternetSearchResponse:
        with httpx.Client(timeout=20.0) as client:  # Exa search api takes ~10-15s
            response = client.post(
                f"{self.host}/search",
                headers=self.headers,
                data=json.dumps(
                    {
                        "query": query,
                        "type": "auto",
                        "numResults": self.num_results,
                        "contents": {
                            "text": True,
                            "livecrawl": "always",
                            "summary": True,
                            "highlights": {
                                "numSentences": 5,
                                "highlightsPerUrl": 1,
                                "query": "Most relevant to the question: {query}",
                            },
                        },
                    }
                ),
            )

            response.raise_for_status()

            results = response.json()

            # Exa always returns results (questionable)
            search_results = results["results"]

            internet_results = []
            for result in search_results:
                try:
                    # Check required fields first
                    required_fields = ["title", "url", "text", "summary", "highlights"]
                    missing_fields = [
                        field for field in required_fields if field not in result
                    ]
                    if missing_fields:
                        logger.warning(
                            f"Missing required fields in search result: {missing_fields}"
                        )
                        continue

                    internet_results.append(
                        InternetSearchResult(
                            title=result["title"],
                            url=result["url"],
                            published_date=result.get(
                                "publishedDate", datetime.now().isoformat()
                            ),
                            author=result.get("author"),
                            score=result.get("score"),
                            full_content=result["text"],
                            relevant_content="\n".join(result["highlights"]),
                            summary=result["summary"],
                        )
                    )
                except Exception as e:
                    logger.error(f"Error processing search result: {e}")
                    continue

            return InternetSearchResponse(
                revised_query=query,
                internet_results=internet_results,
            )

    def embed_internet_search_results(
        self, results: InternetSearchResponse, embedder: DefaultIndexingEmbedder
    ) -> list[DocAwareChunk]:
        documents: list[Document] = []
        for result in results.internet_results:
            # Create a document from the search result
            doc = Document(
                id=result.url,
                sections=[TextSection(link=result.url, text=result.full_content)],
                source=DocumentSource.NOT_APPLICABLE,
                semantic_identifier=result.title,
                metadata={
                    "url": result.url,
                    "published_date": result.published_date,
                    "author": result.author or "Unknown",
                    "score": str(result.score) if result.score else "N/A",
                },
                doc_updated_at=(
                    datetime.fromisoformat(result.published_date)
                    if result.published_date
                    else None
                ),
                title=result.title,
            )

            documents.append(doc)

        indexing_documents = process_image_sections(documents)

        chunker = Chunker(
            tokenizer=embedder.embedding_model.tokenizer,
            enable_multipass=False,
            enable_contextual_rag=False,
        )
        chunks = chunker.chunk(indexing_documents)

        chunks_with_embeddings, _ = (
            embed_chunks_with_failure_handling(
                chunks=chunks,
                embedder=embedder,
            )
            if chunks
            else ([], [])
        )

        return chunks_with_embeddings

    def vector_similarity_sort(
        self, query: list[float], chunks: list[IndexChunk]
    ) -> list[IndexChunk]:
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        # Calculate similarity scores for each chunk
        scored_chunks = []
        for chunk in chunks:
            # Use the full embedding for similarity calculation
            similarity = cosine_similarity(query, chunk.embeddings.full_embedding)
            scored_chunks.append((similarity, chunk))

        # Sort chunks by similarity score in descending order
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # Return just the chunks in order of similarity
        return [chunk for _, chunk in scored_chunks]

    def run(
        self, override_kwargs: None = None, **kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        query = kwargs["internet_search_query"]
        results = self._perform_search(query)

        # Yield initial search response
        yield ToolResponse(id=INTERNET_SEARCH_RESPONSE_ID, response=results)

        search_settings = get_current_search_settings(self.db_session)
        embedder = DefaultIndexingEmbedder.from_db_search_settings(
            search_settings=search_settings
        )
        query_embedding = embedder.embedding_model.encode(
            [query], text_type=EmbedTextType.QUERY
        )[0]
        embedded_chunks = self.embed_internet_search_results(
            results,
            embedder,
        )

        sorted_chunks = self.vector_similarity_sort(query_embedding, embedded_chunks)
        pruned_llm_docs = []
        token_count = 0
        for chunk in sorted_chunks:
            chunk_token_count = len(chunk.embeddings.full_embedding)
            if token_count + chunk_token_count > self.pruning_config.max_tokens:
                break
            token_count += chunk_token_count
            pruned_llm_docs.append(internet_search_chunk_to_llm_doc(chunk))

        yield ToolResponse(
            id=FINAL_CONTEXT_DOCUMENTS_ID,
            response=pruned_llm_docs,
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        search_response = cast(InternetSearchResponse, args[0].response)
        return search_response.model_dump()

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        return build_next_prompt_for_search_like_tool(
            prompt_builder=prompt_builder,
            tool_call_summary=tool_call_summary,
            tool_responses=tool_responses,
            using_tool_calling_llm=using_tool_calling_llm,
            answer_style_config=self.answer_style_config,
            prompt_config=self.prompt_config,
            context_type="internet search results",
        )
