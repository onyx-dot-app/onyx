"""
An explanation of the search tool found below:

Step 1: Queries
- The LLM will generate some queries based on the chat history for what it thinks are the best things to search for.
This has a pretty generic prompt so it's not perfectly tuned for search but provides breadth and also the LLM can often break up
the query into multiple searches which the other flows do not do. Exp: Compare the sales process between company X and Y can be
broken up into "sales process company X" and "sales process company Y".
- A specifial prompt and history is used to generate another query which is best tuned for a semantic/hybrid search pipeline.
- A small set of keyword emphasized queries are also generated to cover additional breadth. This is important for cases where
the query is short, keyword heavy, or has a lot of model unseen terminology.

Step 2: Recombination
We use a weighted RRF to combine the search results from the queries above. Each query will have a list of search results with
some scores however these are downstream of a normalization step so they cannot easily be compared with one another on an
absolute scale. RRF is a good way to combine these and allows us to give some custom weightings. We also merge document chunks
that are adjacent to provide more continuous context to the LLM.

Step 3: Selection
We pass the recombined results (truncated set) to the LLM to select the most promising ones to read. This is to reduce noise and
reduce downstream chances of hallucination. The LLM at this point also has the entire set of document chunks so it has
information across documents not just per document. This also reduces the number of tokens required for the next step.

Step 4: Expansion
For the selected documents, we pass the main retrieved sections from above (this may be a single chunk or a section comprised of
several consecutive chunks) along with chunks above and below the section to the LLM. The LLM determines how much of the document
it wants to read. This is done in parallel for all selected documents. Reason being that the LLM would not be able to do a good
job of this with all of the documents in the prompt at once. Keeping every LLM decision step as simple as possible is key for
reliable performance.

Step 5: Prompt Building
We construct a response string back to the LLM as the result of the tool call. We also pass relevant richer objects back
so that the rest of the code can persist it, render it in the UI, etc. The response is a json that makes it easy for the LLM to
refer to by using matching keywords to other parts of the prompt and reminders.
"""

import time
from collections.abc import Callable
from typing import Any
from typing import cast

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.constants import FederatedConnectorSource
from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkIndexRequest
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.connector import check_connectors_exist
from onyx.db.connector import check_federated_connectors_exist
from onyx.db.federated import (
    get_federated_connector_document_set_mappings_by_document_set_names,
)
from onyx.db.federated import list_federated_connector_oauth_tokens
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.slack_bot import fetch_slack_bots
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.onyxbot.slack.models import SlackContext
from onyx.secondary_llm_flows.document_filter import select_chunks_for_relevance
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from onyx.secondary_llm_flows.query_expansion import keyword_query_expansion
from onyx.secondary_llm_flows.query_expansion import semantic_query_rephrase
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.interface import Tool
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.constants import (
    KEYWORD_QUERY_HYBRID_ALPHA,
)
from onyx.tools.tool_implementations.search.constants import (
    LLM_KEYWORD_QUERY_WEIGHT,
)
from onyx.tools.tool_implementations.search.constants import (
    LLM_NON_CUSTOM_QUERY_WEIGHT,
)
from onyx.tools.tool_implementations.search.constants import (
    LLM_SEMANTIC_QUERY_WEIGHT,
)
from onyx.tools.tool_implementations.search.constants import (
    MAX_CHUNKS_FOR_RELEVANCE,
)
from onyx.tools.tool_implementations.search.constants import ORIGINAL_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.search_utils import (
    expand_section_with_context,
)
from onyx.tools.tool_implementations.search.search_utils import (
    merge_overlapping_sections,
)
from onyx.tools.tool_implementations.search.search_utils import (
    weighted_reciprocal_rank_fusion,
)
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

logger = setup_logger()

QUERIES_FIELD = "queries"


def deduplicate_queries(
    queries_with_weights: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """Deduplicate queries by case-insensitive comparison and sum weights.

    Args:
        queries_with_weights: List of (query, weight) tuples

    Returns:
        Deduplicated list of (query, weight) tuples with summed weights
    """
    query_map: dict[str, tuple[str, float]] = {}
    for query, weight in queries_with_weights:
        query_lower = query.lower()
        if query_lower in query_map:
            # Sum weights for duplicate queries
            existing_query, existing_weight = query_map[query_lower]
            query_map[query_lower] = (existing_query, existing_weight + weight)
        else:
            # Keep the first occurrence (preserves original casing)
            query_map[query_lower] = (query, weight)
    return list(query_map.values())


def _estimate_section_tokens(
    section: InferenceSection,
    token_counter: Callable[[str], int],
    max_chunks_per_section: int | None = None,
) -> int:
    """Estimate token count for a section using the LLM tokenizer.

    Args:
        section: InferenceSection to estimate tokens for
        token_counter: Function that counts tokens in text
        max_chunks_per_section: Maximum chunks to consider per section (None for all)

    Returns:
        Token count for the section
    """
    # Estimate for metadata (title, source_type, etc.)
    METADATA_TOKEN_ESTIMATE = 75

    # If max_chunks_per_section is specified, only count tokens for selected chunks
    if max_chunks_per_section is not None:
        selected_chunks = select_chunks_for_relevance(section, max_chunks_per_section)
        # Combine content from selected chunks
        combined_content = "\n".join(chunk.content for chunk in selected_chunks)
        content_tokens = token_counter(combined_content)
    else:
        content_tokens = token_counter(section.combined_content)

    return content_tokens + METADATA_TOKEN_ESTIMATE


@log_function_time(print_only=True)
def _trim_sections_by_tokens(
    sections: list[InferenceSection],
    max_tokens: int,
    token_counter: Callable[[str], int],
    max_chunks_per_section: int | None = None,
) -> list[InferenceSection]:
    """Trim sections to fit within a token budget using the LLM tokenizer.

    Args:
        sections: List of InferenceSection objects to trim
        max_tokens: Maximum token budget
        token_counter: Function that counts tokens in text
        max_chunks_per_section: Maximum chunks to consider per section (None for all)

    Returns:
        Trimmed list of sections that fit within the token budget
    """
    if not sections or max_tokens <= 0:
        return sections

    trimmed_sections = []
    total_tokens = 0

    for section in sections:
        section_tokens = _estimate_section_tokens(
            section, token_counter, max_chunks_per_section
        )
        if total_tokens + section_tokens <= max_tokens:
            trimmed_sections.append(section)
            total_tokens += section_tokens
        else:
            break

    logger.debug(
        f"Trimmed sections from {len(sections)} to {len(trimmed_sections)} "
        f"({total_tokens} tokens, budget: {max_tokens})"
    )

    return trimmed_sections


class SearchTool(Tool[SearchToolOverrideKwargs]):
    NAME = "internal_search"
    DISPLAY_NAME = "Internal Search"
    DESCRIPTION = "Search connected applications for information."

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
        # Used for ACLs and federated search
        user: User | None,
        # Used for filter settings
        persona: Persona,
        llm: LLM,
        document_index: DocumentIndex,
        # Respecting user selections
        user_selected_filters: BaseFilters | None,
        # If the chat is part of a project
        project_id: int | None,
        bypass_acl: bool = False,
        # Slack context for federated Slack search (tokens fetched internally)
        slack_context: SlackContext | None = None,
    ) -> None:
        super().__init__(emitter=emitter)

        self.user = user
        self.persona = persona
        self.llm = llm
        self.document_index = document_index
        self.user_selected_filters = user_selected_filters
        self.project_id = project_id
        self.bypass_acl = bypass_acl
        self.slack_context = slack_context

        # Store session factory instead of session for thread-safety
        # When tools are called in parallel, each thread needs its own session
        self._session_bind = db_session.get_bind()
        self._session_factory = sessionmaker(bind=self._session_bind)

        self._id = tool_id

    def _get_thread_safe_session(self) -> Session:
        """Create a new database session for the current thread. Note this is only safe for the ORM caches/identity maps,
        pending objects, flush state, etc. But it is still using the same underlying database connection.

        This ensures thread-safety when the search tool is called in parallel.
        Each parallel execution gets its own isolated database session with
        its own transaction scope.

        Returns:
            A new SQLAlchemy Session instance
        """
        return self._session_factory()

    def _run_slack_search(self, query: str) -> list[InferenceChunk]:
        """Run Slack federated search for a query.

        This runs in parallel with the main Vespa search to avoid
        query multiplication issues where each Vespa query variation
        would trigger a separate Slack search.

        Tokens are fetched internally based on:
        1. Slack bot context (if slack_context is set)
        2. User's federated OAuth token (for web users)

        Args:
            query: The user's original search query

        Returns:
            List of InferenceChunk results from Slack
        """
        db_session = self._get_thread_safe_session()
        try:
            # Determine Slack access tokens
            bot_token: str | None = None
            access_token: str | None = None
            entities: dict[str, Any] = {}

            # Case 1: Slack bot context - requires Slack federated connector
            # linked via persona's document sets (matches old behavior)
            if self.slack_context:
                # Step 1: Look up document sets associated with the persona
                document_set_names = [ds.name for ds in self.persona.document_sets]
                if not document_set_names:
                    logger.debug(
                        "Skipping Slack federated search: no document sets on persona"
                    )
                    return []

                # Step 2: Find Slack federated connector associated with those document sets
                slack_federated_mappings = (
                    get_federated_connector_document_set_mappings_by_document_set_names(
                        db_session, document_set_names
                    )
                )
                found_slack_connector = False
                for mapping in slack_federated_mappings:
                    if (
                        mapping.federated_connector is not None
                        and mapping.federated_connector.source
                        == FederatedConnectorSource.FEDERATED_SLACK
                    ):
                        # Step 3: Use slack_federated_connector_config from that connector
                        entities = mapping.federated_connector.config or {}
                        found_slack_connector = True
                        logger.debug(
                            f"Found Slack federated connector config: {entities}"
                        )
                        break

                if not found_slack_connector:
                    # No Slack federated connector found in document sets
                    logger.debug(
                        "Skipping Slack federated search: no Slack federated connector "
                        f"linked to document sets {document_set_names}"
                    )
                    return []

                # Now fetch the bot tokens
                try:
                    slack_bots = fetch_slack_bots(db_session)
                    # Find an enabled bot with user_token (preferred) or bot_token
                    tenant_slack_bot = next(
                        (bot for bot in slack_bots if bot.enabled and bot.user_token),
                        None,
                    )
                    if not tenant_slack_bot:
                        tenant_slack_bot = next(
                            (bot for bot in slack_bots if bot.enabled), None
                        )

                    if tenant_slack_bot:
                        bot_token = tenant_slack_bot.bot_token
                        access_token = (
                            tenant_slack_bot.user_token or tenant_slack_bot.bot_token
                        )
                except Exception as e:
                    logger.warning(f"Could not fetch Slack bot tokens: {e}")

            # Case 2: Web user with federated OAuth (if not already configured)
            if not access_token and self.user:
                try:
                    federated_oauth_tokens = list_federated_connector_oauth_tokens(
                        db_session, self.user.id
                    )
                    slack_oauth_token = next(
                        (
                            token
                            for token in federated_oauth_tokens
                            if token.federated_connector.source
                            == FederatedConnectorSource.FEDERATED_SLACK
                        ),
                        None,
                    )

                    if slack_oauth_token:
                        access_token = slack_oauth_token.token
                        entities = slack_oauth_token.federated_connector.config or {}
                except Exception as e:
                    logger.warning(f"Could not fetch Slack OAuth token: {e}")

            if not access_token:
                return []

            chunk_request = ChunkIndexRequest(
                query=query,
                filters=IndexFilters(access_control_list=None),
            )

            chunks = slack_retrieval(
                query=chunk_request,
                access_token=access_token,
                db_session=db_session,
                connector=None,
                entities=entities,
                limit=None,
                slack_event_context=self.slack_context,
                bot_token=bot_token,
                team_id=None,
            )

            logger.info(f"Slack federated search returned {len(chunks)} chunks")
            return chunks

        except Exception as e:
            logger.error(f"Slack federated search error: {e}", exc_info=True)
            return []

        finally:
            db_session.close()

    def _run_search_for_query(
        self,
        query: str,
        hybrid_alpha: float | None,
        num_hits: int,
    ) -> list[InferenceChunk]:
        """Run search pipeline for a single query.

        Args:
            query: The search query string
            hybrid_alpha: Hybrid search alpha parameter (None for default)
            num_hits: Maximum number of hits to return

        Returns:
            List of InferenceChunk results
        """
        # Create a thread-safe session for this search
        search_db_session = self._get_thread_safe_session()
        try:
            return search_pipeline(
                db_session=search_db_session,
                chunk_search_request=ChunkSearchRequest(
                    query=query,
                    hybrid_alpha=hybrid_alpha,
                    # For projects, the search scope is the project and has no other limits
                    user_selected_filters=(
                        self.user_selected_filters if self.project_id is None else None
                    ),
                    bypass_acl=self.bypass_acl,
                    limit=num_hits,
                ),
                project_id=self.project_id,
                document_index=self.document_index,
                user=self.user,
                persona=self.persona,
            )
        finally:
            search_db_session.close()

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Check if search tool is available.

        The search tool is available if ANY of the following exist:
        - Regular connectors (team knowledge)
        - Federated connectors (e.g., Slack)
        - User files (User Knowledge mode)
        """
        from onyx.db.connector import check_user_files_exist

        return (
            check_connectors_exist(db_session)
            or check_federated_connectors_exist(db_session)
            or check_user_files_exist(db_session)
        )

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    """For explicit tool calling"""

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        QUERIES_FIELD: {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of search queries to execute, typically a single query.",
                        },
                    },
                    "required": [QUERIES_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolStart(),
            )
        )

    @log_function_time(print_only=True)
    def run(
        self,
        placement: Placement,
        override_kwargs: SearchToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        # Start overall timing
        overall_start_time = time.time()

        # Initialize timing variables (in case of early exceptions)
        query_expansion_elapsed = 0.0
        document_selection_elapsed = 0.0
        document_expansion_elapsed = 0.0

        # Create a new thread-safe session for this execution
        # This prevents transaction conflicts when multiple search tools run in parallel
        db_session = self._get_thread_safe_session()
        try:
            llm_queries = cast(list[str], llm_kwargs[QUERIES_FIELD])

            # Run semantic and keyword query expansion in parallel (unless skipped)
            # Use message history, memories, and user info from override_kwargs
            message_history = (
                override_kwargs.message_history
                if override_kwargs.message_history
                else []
            )
            memories = override_kwargs.memories
            user_info = override_kwargs.user_info

            # Skip query expansion if this is a repeat search call
            if override_kwargs.skip_query_expansion:
                logger.debug(
                    "Search tool - Skipping query expansion (repeat search call)"
                )
                semantic_query = None
                keyword_queries: list[str] = []
            else:
                # Start timing for query expansion/rephrase
                query_expansion_start_time = time.time()

                functions_with_args: list[tuple[Callable, tuple]] = [
                    (
                        semantic_query_rephrase,
                        (message_history, self.llm, user_info, memories),
                    ),
                    (
                        keyword_query_expansion,
                        (message_history, self.llm, user_info, memories),
                    ),
                ]

                expansion_results = run_functions_tuples_in_parallel(
                    functions_with_args
                )

                # End timing for query expansion/rephrase
                query_expansion_elapsed = time.time() - query_expansion_start_time
                logger.debug(
                    f"Search tool - Query expansion/rephrase took {query_expansion_elapsed:.3f} seconds"
                )
                semantic_query = expansion_results[0]  # str
                keyword_queries = (
                    expansion_results[1] if expansion_results[1] is not None else []
                )  # list[str]

            # Prepare queries with their weights and hybrid_alpha settings
            # Group 1: Keyword queries (use hybrid_alpha=0.2)
            keyword_queries_with_weights = [
                (kw_query, LLM_KEYWORD_QUERY_WEIGHT) for kw_query in keyword_queries
            ]
            deduplicated_keyword_queries = deduplicate_queries(
                keyword_queries_with_weights
            )

            # Group 2: Semantic/LLM/Original queries (use hybrid_alpha=None)
            # Include all LLM-provided queries with their weight
            semantic_queries_with_weights = (
                [
                    (semantic_query, LLM_SEMANTIC_QUERY_WEIGHT),
                ]
                if semantic_query
                else []
            )
            for llm_query in llm_queries:
                # In rare cases, the LLM may fail to provide real queries
                if llm_query:
                    semantic_queries_with_weights.append(
                        (llm_query, LLM_NON_CUSTOM_QUERY_WEIGHT)
                    )
            if override_kwargs.original_query:
                semantic_queries_with_weights.append(
                    (override_kwargs.original_query, ORIGINAL_QUERY_WEIGHT)
                )
            deduplicated_semantic_queries = deduplicate_queries(
                semantic_queries_with_weights
            )

            # Build the all_queries list for UI display, sorted by weight (highest first)
            # Combine all deduplicated queries and sort by weight
            all_queries_with_weights = (
                deduplicated_semantic_queries + deduplicated_keyword_queries
            )
            all_queries_with_weights.sort(key=lambda x: x[1], reverse=True)

            # Extract queries in weight order, handling cross-duplicates
            all_queries = []
            seen_lower = set()
            for query, _ in all_queries_with_weights:
                query_lower = query.lower()
                if query_lower not in seen_lower:
                    all_queries.append(query)
                    seen_lower.add(query_lower)

            logger.debug(
                f"All Queries (sorted by weight): {all_queries}, "
                f"Keyword queries: {[q for q, _ in deduplicated_keyword_queries]}"
            )

            # Emit the queries early so the UI can display them immediately
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=SearchToolQueriesDelta(
                        queries=all_queries,
                    ),
                )
            )

            # Run all searches in parallel with appropriate hybrid_alpha values
            # Keyword queries use hybrid_alpha=0.2 (favor keyword search)
            # Other queries use default hybrid_alpha (balanced semantic/keyword)
            search_functions: list[tuple[Callable, tuple]] = []
            search_weights: list[float] = []

            # Add deduplicated semantic queries (use hybrid_alpha=None)
            for query, weight in deduplicated_semantic_queries:
                search_functions.append(
                    (
                        self._run_search_for_query,
                        (query, None, override_kwargs.num_hits),
                    )
                )
                search_weights.append(weight)

            # Add deduplicated keyword queries (use hybrid_alpha=0.2)
            for query, weight in deduplicated_keyword_queries:
                search_functions.append(
                    (
                        self._run_search_for_query,
                        (query, KEYWORD_QUERY_HYBRID_ALPHA, override_kwargs.num_hits),
                    )
                )
                search_weights.append(weight)

            # Add Slack federated search (runs once in parallel with all Vespa queries)
            # This avoids the query multiplication problem where each Vespa query
            # would trigger a separate Slack search
            # Run if we have slack_context (bot) or user (might have OAuth token)
            if (self.slack_context or self.user) and override_kwargs.original_query:
                search_functions.append(
                    (
                        self._run_slack_search,
                        (override_kwargs.original_query,),
                    )
                )
                # Use same weight as original query for Slack results
                search_weights.append(ORIGINAL_QUERY_WEIGHT)

            # Run all searches in parallel (Vespa queries + Slack)
            all_search_results = run_functions_tuples_in_parallel(search_functions)

            # Merge results using weighted Reciprocal Rank Fusion
            # This intelligently combines rankings from different queries
            top_chunks = weighted_reciprocal_rank_fusion(
                ranked_results=all_search_results,
                weights=search_weights,
                id_extractor=lambda chunk: f"{chunk.document_id}_{chunk.chunk_id}",
            )

            # We can disregard all of the chunks that exceed the num_hits parameter since it's not valid to have
            # documents/contents from things that aren't returned to the user on the frontend
            top_sections = merge_individual_chunks(top_chunks)[
                : override_kwargs.num_hits
            ]

            # Convert InferenceSections to SearchDocs for emission
            search_docs = convert_inference_sections_to_search_docs(
                top_sections, is_internet=False
            )

            secondary_flows_user_query = (
                override_kwargs.original_query
                or semantic_query
                or (llm_queries[0] if llm_queries else "")
            )

            token_counter = get_llm_token_counter(self.llm)

            # Trim sections to fit within token budget before LLM selection
            # This is to account for very short chunks flooding the search context
            # Only consider MAX_CHUNKS_FOR_RELEVANCE chunks per section to avoid flooding from
            # documents with many matching sections
            max_tokens_for_selection = (
                override_kwargs.max_llm_chunks or MAX_CHUNKS_FED_TO_CHAT
            ) * DOC_EMBEDDING_CONTEXT_SIZE

            # This is approximate since it doesn't build the exact string of the call below
            # Some things are estimated and may be under (like the metadata tokens)
            sections_for_selection = _trim_sections_by_tokens(
                sections=top_sections,
                max_tokens=max_tokens_for_selection,
                token_counter=token_counter,
                max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
            )

            # Start timing for LLM document selection
            document_selection_start_time = time.time()

            # Use LLM to select the most relevant sections for expansion
            selected_sections, best_doc_ids = select_sections_for_expansion(
                sections=sections_for_selection,
                user_query=secondary_flows_user_query,
                llm=self.llm,
                max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
            )

            # End timing for LLM document selection
            document_selection_elapsed = time.time() - document_selection_start_time
            logger.debug(
                f"Search tool - LLM picking documents took {document_selection_elapsed:.3f} seconds "
                f"(selected {len(selected_sections)} sections)"
            )

            # Create a set of best document IDs for quick lookup
            best_doc_ids_set = set(best_doc_ids) if best_doc_ids else set()

            # To show the users, we only pass in the docs that are determined to be good by the LLM
            final_ui_docs = convert_inference_sections_to_search_docs(
                selected_sections, is_internet=False
            )

            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=SearchToolDocumentsDelta(
                        documents=final_ui_docs,
                    ),
                )
            )

            # Create wrapper function to handle errors gracefully
            def expand_section_safe(
                section: InferenceSection,
                user_query: str,
                llm: LLM,
                document_index: DocumentIndex,
                expand_override: bool,
            ) -> InferenceSection:
                """Wrapper that handles exceptions and returns original section on error."""
                try:
                    expanded_section = expand_section_with_context(
                        section=section,
                        user_query=user_query,
                        llm=llm,
                        document_index=document_index,
                        expand_override=expand_override,
                    )
                    # Return expanded section if not None, otherwise original
                    return expanded_section if expanded_section is not None else section
                except Exception as e:
                    logger.warning(
                        f"Error processing section context expansion: {e}. Using original section."
                    )
                    return section

            # Build parallel function calls for all sections
            expansion_functions: list[tuple[Callable, tuple]] = [
                (
                    expand_section_safe,
                    (
                        section,
                        secondary_flows_user_query,
                        self.llm,
                        self.document_index,
                        section.center_chunk.document_id in best_doc_ids_set,
                    ),
                )
                for section in selected_sections
            ]

            # Start timing for document expansion
            document_expansion_start_time = time.time()

            # Run all expansions in parallel
            expanded_sections = run_functions_tuples_in_parallel(expansion_functions)

            # End timing for document expansion
            document_expansion_elapsed = time.time() - document_expansion_start_time
            logger.debug(
                f"Search tool - Expansion of selected documents took {document_expansion_elapsed:.3f} seconds "
                f"(expanded {len(expanded_sections)} sections)"
            )

            if not expanded_sections:
                expanded_sections = selected_sections

            # Merge sections from the same document that have adjacent or overlapping chunks
            # This prevents duplicate content and reduces token usage
            merged_sections = merge_overlapping_sections(expanded_sections)

            docs_str, citation_mapping = convert_inference_sections_to_llm_string(
                top_sections=merged_sections,
                citation_start=override_kwargs.starting_citation_num,
                limit=override_kwargs.max_llm_chunks,
                include_document_id=True,
            )

            # End overall timing
            overall_elapsed = time.time() - overall_start_time
            logger.debug(
                f"Search tool - Total execution time: {overall_elapsed:.3f} seconds "
                f"(query expansion: {query_expansion_elapsed:.3f}s, "
                f"document selection: {document_selection_elapsed:.3f}s, "
                f"document expansion: {document_expansion_elapsed:.3f}s)"
            )

            # TODO: extension - this can include the smaller set of approved docs to be saved/displayed in the UI
            # for replaying. Currently the full set is returned and saved.
            return ToolResponse(
                # Typically the rich response will give more docs in case it needs to be displayed in the UI
                rich_response=SearchDocsResponse(
                    search_docs=search_docs, citation_mapping=citation_mapping
                ),
                # The LLM facing response typically includes less docs to cut down on noise and token usage
                llm_facing_response=docs_str,
            )

        finally:
            # Always close the session to release database connections
            db_session.close()
