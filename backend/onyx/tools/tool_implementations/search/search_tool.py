"""
An explanation of the search tool found below:

Step 1: Queries
- The LLM provides the queries directly in the tool call as two lists: `semantic_queries` (full
natural-language standalone questions) and `keyword_queries` (keyword-only variations/expansions).
At least one of the two must be non-empty. Semantic queries run through the default hybrid search;
keyword queries run as pure keyword (BM25) searches with no embedding step.
- On the first search call of each user turn, a custom-prompted semantic rephrase of the user's
message is additionally generated, used as an extra (highest-weighted) semantic query, and surfaced
back to the LLM as `automatic_semantic_expansion` so it knows no further automatic expansion will
happen on repeat calls.

Step 2: Recombination
We use a weighted RRF to combine the search results from the queries above. Each query will have a
list of search results with some scores however these are downstream of a normalization step so
they cannot easily be compared with one another on an absolute scale. RRF is a good way to combine
these and allows us to give some custom weightings. We also merge document chunks that are adjacent
to provide more continuous context to the LLM. The merged list beyond the returned window is cached
(per `search_query_id`) for the duration of the request so the `paginate_search_results` companion
tool can serve deeper pages — re-querying the document index with an offset when the cache runs out.

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
refer to by using matching keywords to other parts of the prompt and reminders. The payload carries the `search_query_id` the
LLM needs for pagination.
"""

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.constants import FederatedConnectorSource
from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkIndexRequest
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import PersonaSearchInfo
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.context.search.utils import populate_file_ids_on_sections
from onyx.db.connector import check_connectors_exist
from onyx.db.connector import check_federated_connectors_exist
from onyx.db.document_set import filter_document_set_names_by_user_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.federated import (
    get_federated_connector_document_set_mappings_by_document_set_names,
)
from onyx.db.federated import list_federated_connector_oauth_tokens
from onyx.db.models import SearchSettings
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.slack_bot import fetch_slack_bots
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.federated_connectors.federated_retrieval import FederatedRetrievalInfo
from onyx.federated_connectors.federated_retrieval import (
    get_federated_retrieval_functions,
)
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.onyxbot.slack.models import SlackContext
from onyx.secondary_llm_flows.document_filter import select_chunks_for_relevance
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from onyx.secondary_llm_flows.query_expansion import semantic_query_rephrase
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.interface import Tool
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.constants import KEYWORD_ONLY_HYBRID_ALPHA
from onyx.tools.tool_implementations.search.constants import LLM_SEMANTIC_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.constants import MAX_CHUNKS_FOR_RELEVANCE
from onyx.tools.tool_implementations.search.constants import MODEL_KEYWORD_QUERY_WEIGHT
from onyx.tools.tool_implementations.search.constants import MODEL_SEMANTIC_QUERY_WEIGHT
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
from onyx.tools.tool_implementations.search.turn_state import ExecutedQuerySpec
from onyx.tools.tool_implementations.search.turn_state import SearchEntry
from onyx.tools.tool_implementations.search.turn_state import SearchToolTurnState
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT

logger = setup_logger()

SEMANTIC_QUERIES_FIELD = "semantic_queries"
KEYWORD_QUERIES_FIELD = "keyword_queries"


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
        "Trimmed sections from %s to %s (%s tokens, budget: %s)",
        len(sections),
        len(trimmed_sections),
        total_tokens,
        max_tokens,
    )

    return trimmed_sections


def _coerce_query_list(raw: Any) -> list[str]:
    """Coerce an LLM-provided query list arg into a clean list of strings.

    Tolerates a bare string (some models send one instead of a single-element
    array) and drops empty/whitespace-only entries.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [query.strip() for query in raw if isinstance(query, str) and query.strip()]


def _expand_section_safe(
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
            "Error processing section context expansion: %s. Using original section.",
            e,
        )
        return section


def run_post_retrieval_pipeline(
    sections: list[InferenceSection],
    user_query: str,
    llm: LLM,
    document_index: DocumentIndex,
    emitter: Emitter,
    placement: Placement,
    starting_citation_num: int,
    max_llm_chunks: int | None,
    include_link: bool,
    search_query_id: int | None = None,
    page: int | None = None,
    automatic_semantic_expansion: str | None = None,
) -> ToolResponse:
    """Steps 3-5 of the search flow (see module docstring): LLM relevance
    selection, context expansion, section merging, and response building for a
    window of RRF-merged sections.

    Shared by SearchTool (page 0) and PaginateSearchResultsTool (pages >= 1) so
    every page of a search gets the identical treatment.
    """
    # Enrich chunks with `Document.file_id` (Postgres-only metadata not
    # stored in the document index).
    with get_session_with_current_tenant() as enrichment_session:
        populate_file_ids_on_sections(sections, enrichment_session)

    # Convert InferenceSections to SearchDocs for emission
    search_docs = convert_inference_sections_to_search_docs(sections, is_internet=False)

    token_counter = get_llm_token_counter(llm)

    # Trim sections to fit within token budget before LLM selection
    # This is to account for very short chunks flooding the search context
    # Only consider MAX_CHUNKS_FOR_RELEVANCE chunks per section to avoid flooding from
    # documents with many matching sections
    max_tokens_for_selection = (
        max_llm_chunks or MAX_CHUNKS_FED_TO_CHAT
    ) * DOC_EMBEDDING_CONTEXT_SIZE

    # This is approximate since it doesn't build the exact string of the call below
    # Some things are estimated and may be under (like the metadata tokens)
    sections_for_selection = _trim_sections_by_tokens(
        sections=sections,
        max_tokens=max_tokens_for_selection,
        token_counter=token_counter,
        max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
    )

    document_selection_start_time = time.time()

    # Use LLM to select the most relevant sections for expansion
    selected_sections, best_doc_ids = select_sections_for_expansion(
        sections=sections_for_selection,
        user_query=user_query,
        llm=llm,
        max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
    )

    document_selection_elapsed = time.time() - document_selection_start_time
    logger.debug(
        "Search tool - LLM picking documents took %s seconds (selected %s sections)",
        format(document_selection_elapsed, ".3f"),
        len(selected_sections),
    )

    # Create a set of best document IDs for quick lookup
    best_doc_ids_set = set(best_doc_ids) if best_doc_ids else set()

    # To show the users, we only pass in the docs that are determined to be good by the LLM
    final_ui_docs = convert_inference_sections_to_search_docs(
        selected_sections, is_internet=False
    )

    emitter.emit(
        Packet(
            placement=placement,
            obj=SearchToolDocumentsDelta(
                documents=final_ui_docs,
            ),
        )
    )

    # Build parallel function calls for all sections
    expansion_functions: list[tuple[Callable, tuple]] = [
        (
            _expand_section_safe,
            (
                section,
                user_query,
                llm,
                document_index,
                section.center_chunk.document_id in best_doc_ids_set,
            ),
        )
        for section in selected_sections
    ]

    document_expansion_start_time = time.time()

    # Run all expansions in parallel
    expanded_sections = run_functions_tuples_in_parallel(expansion_functions)

    document_expansion_elapsed = time.time() - document_expansion_start_time
    logger.debug(
        "Search tool - Expansion of selected documents took %s seconds (expanded %s sections)",
        format(document_expansion_elapsed, ".3f"),
        len(expanded_sections),
    )

    if not expanded_sections:
        expanded_sections = selected_sections

    # Merge sections from the same document that have adjacent or overlapping chunks
    # This prevents duplicate content and reduces token usage
    merged_sections = merge_overlapping_sections(expanded_sections)

    docs_str, citation_mapping = convert_inference_sections_to_llm_string(
        top_sections=merged_sections,
        citation_start=starting_citation_num,
        limit=max_llm_chunks,
        include_document_id=False,
        include_link=include_link,
        search_query_id=search_query_id,
        page=page,
        automatic_semantic_expansion=automatic_semantic_expansion,
    )

    return ToolResponse(
        # Typically the rich response will give more docs in case it needs to be displayed in the UI
        rich_response=SearchDocsResponse(
            search_docs=search_docs,
            citation_mapping=citation_mapping,
            displayed_docs=final_ui_docs,
        ),
        # The LLM facing response typically includes less docs to cut down on noise and token usage
        llm_facing_response=docs_str,
    )


class SearchTool(Tool[SearchToolOverrideKwargs]):
    NAME = "internal_search"
    DISPLAY_NAME = "Internal Search"
    DESCRIPTION = (
        "Search indexed applications for information. Provide two lists of queries in a "
        "single call: `semantic_queries` and `keyword_queries` — you may use either or both "
        "(at least one is required). It is recommended to always use an expanded set of "
        "queries, for example, 3 semantic queries and 3 keyword queries. For semantic "
        "queries, each should be fully natural language and a complete standalone question, "
        "typically very similar to the user's ask; do not simplify or truncate the query, "
        "should be specific and natural. For keyword queries, only extract the most relevant "
        "keywords and try to create variations or expansions using synonyms or other forms "
        "of the key terms. Every result includes a `search_query_id`; to fetch more results "
        "for this search, call the `paginate_search_results` tool with that id and the next "
        "page number rather than repeating the same queries."
    )

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        # Used for ACLs and federated search, anonymous users only see public docs
        user: User,
        # Pre-extracted persona search configuration
        persona_search_info: PersonaSearchInfo,
        llm: LLM,
        document_index: DocumentIndex,
        # Respecting user selections
        user_selected_filters: BaseFilters | None,
        # Vespa metadata filters for overflowing user files.  NOT the raw IDs
        # of the current project/persona — only set when user files couldn't
        # fit in the LLM context and need to be searched via vector DB.
        project_id_filter: int | None,
        persona_id_filter: int | None = None,
        bypass_acl: bool = False,
        # Slack context for federated Slack search (tokens fetched internally)
        slack_context: SlackContext | None = None,
        # Whether to enable Slack federated search
        enable_slack_search: bool = True,
        # Shared with PaginateSearchResultsTool; holds search-query ids and the
        # cached result tails for pagination. A private one is created when the
        # caller doesn't supply one (standalone Search API usage).
        turn_state: SearchToolTurnState | None = None,
    ) -> None:
        super().__init__(emitter=emitter)

        self.user = user
        self.persona_search_info = persona_search_info
        self.llm = llm
        self.document_index = document_index
        self.user_selected_filters = user_selected_filters
        self.project_id_filter = project_id_filter
        self.persona_id_filter = persona_id_filter
        self.bypass_acl = bypass_acl
        self.slack_context = slack_context
        self.enable_slack_search = enable_slack_search
        self.turn_state = (
            turn_state if turn_state is not None else SearchToolTurnState()
        )

        self._id = tool_id

    def _prefetch_slack_data(
        self, db_session: Session
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        """Pre-fetch Slack access token, bot token, and entity config from DB.

        All DB queries for Slack federated search are performed here in a
        single session, so the parallel search phase needs no DB access.

        Returns:
            (access_token, bot_token, entities) — access_token is None when
            Slack search should be skipped.
        """
        bot_token: str | None = None
        access_token: str | None = None
        entities: dict[str, Any] = {}

        # Case 1: Slack bot context — requires a Slack federated connector
        # linked via the persona's document sets
        if self.slack_context:
            document_set_names = self.persona_search_info.document_set_names
            if not document_set_names:
                logger.debug(
                    "Skipping Slack federated search: no document sets on persona"
                )
                return None, None, {}

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
                    entities = mapping.federated_connector.config or {}
                    found_slack_connector = True
                    logger.debug("Found Slack federated connector config: %s", entities)
                    break

            if not found_slack_connector:
                logger.debug(
                    "Skipping Slack federated search: no Slack federated connector linked to document sets %s",
                    document_set_names,
                )
                return None, None, {}

            try:
                slack_bots = fetch_slack_bots(db_session)
                if not slack_bots:
                    return None, None, {}

                tenant_slack_bot = next(
                    (bot for bot in slack_bots if bot.enabled and bot.user_token),
                    None,
                )
                if not tenant_slack_bot:
                    tenant_slack_bot = next(
                        (bot for bot in slack_bots if bot.enabled), None
                    )

                if tenant_slack_bot:
                    bot_token = (
                        tenant_slack_bot.bot_token.get_value(apply_mask=False)
                        if tenant_slack_bot.bot_token
                        else None
                    )
                    user_token = (
                        tenant_slack_bot.user_token.get_value(apply_mask=False)
                        if tenant_slack_bot.user_token
                        else None
                    )
                    access_token = user_token or bot_token
            except Exception as e:
                logger.warning("Could not fetch Slack bot tokens: %s", e)

        # Case 2: Web user with federated OAuth (if bot context didn't yield a token)
        if not access_token and self.user:
            try:
                federated_oauth_tokens = list_federated_connector_oauth_tokens(
                    db_session, self.user.id
                )
                if not federated_oauth_tokens:
                    return access_token, bot_token, entities

                slack_oauth_token = next(
                    (
                        token
                        for token in federated_oauth_tokens
                        if token.federated_connector.source
                        == FederatedConnectorSource.FEDERATED_SLACK
                    ),
                    None,
                )
                if slack_oauth_token and slack_oauth_token.token:
                    access_token = slack_oauth_token.token.get_value(apply_mask=False)
                    entities = slack_oauth_token.federated_connector.config or {}
            except Exception as e:
                logger.warning("Could not fetch Slack OAuth token: %s", e)

        return access_token, bot_token, entities

    def _run_slack_search(
        self,
        query: str,
        access_token: str,
        bot_token: str | None,
        entities: dict[str, Any],
        search_settings: SearchSettings,
    ) -> list[InferenceChunk]:
        """Run Slack federated search using pre-fetched tokens and config.

        All DB data is pre-fetched in run() so this method needs no DB session.

        Args:
            query: The user's original search query
            access_token: Slack access token (user or bot)
            bot_token: Slack bot token (for enhanced permissions)
            entities: Federated connector entity config (channel filtering)
            search_settings: Pre-fetched SearchSettings for chunking config

        Returns:
            List of InferenceChunk results from Slack
        """
        try:
            chunk_request = ChunkIndexRequest(
                query=query,
                filters=IndexFilters(access_control_list=None),
            )

            chunks = slack_retrieval(
                query=chunk_request,
                access_token=access_token,
                connector=None,
                entities=entities,
                limit=None,
                slack_event_context=self.slack_context,
                bot_token=bot_token,
                team_id=None,
                search_settings=search_settings,
            )

            logger.info("Slack federated search returned %s chunks", len(chunks))
            return chunks

        except Exception as e:
            logger.error("Slack federated search error: %s", e, exc_info=True)
            return []

    def _run_search_for_query(
        self,
        query: str,
        hybrid_alpha: float | None,
        num_hits: int,
        acl_filters: list[str] | None,
        embedding_model: EmbeddingModel,
        federated_retrieval_infos: list[FederatedRetrievalInfo],
        effective_filters: BaseFilters | None,
    ) -> list[InferenceChunk]:
        """Run search pipeline for a single query using pre-fetched data.

        All DB data (ACL filters, embedding model, federated retrieval info)
        is pre-fetched in run() so this method needs no DB session.

        Args:
            query: The search query string
            hybrid_alpha: Hybrid search alpha parameter (None for default)
            num_hits: Maximum number of hits to return
            acl_filters: Pre-fetched ACL filters (None when bypass_acl)
            embedding_model: Pre-fetched embedding model
            federated_retrieval_infos: Pre-fetched federated retrieval functions
            effective_filters: Filters for THIS search, with the per-call source
                scope already applied (computed once in run()).

        Returns:
            List of InferenceChunk results
        """
        return search_pipeline(
            chunk_search_request=ChunkSearchRequest(
                query=query,
                hybrid_alpha=hybrid_alpha,
                # For projects, the search scope is the project and has no other limits
                user_selected_filters=(
                    effective_filters if self.project_id_filter is None else None
                ),
                bypass_acl=self.bypass_acl,
                limit=num_hits,
            ),
            project_id_filter=self.project_id_filter,
            persona_id_filter=self.persona_id_filter,
            document_index=self.document_index,
            user=self.user,
            persona_search_info=self.persona_search_info,
            acl_filters=acl_filters,
            embedding_model=embedding_model,
            prefetched_federated_retrieval_infos=federated_retrieval_infos,
        )

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Check if search tool is available.

        Returns False when the vector DB is disabled (search cannot function
        without it). Otherwise, available if ANY of the following exist:
        - Regular connectors (team knowledge)
        - Federated connectors (e.g., Slack)
        - User files (User Knowledge mode)
        """
        from onyx.configs.app_configs import DISABLE_VECTOR_DB
        from onyx.db.connector import check_user_files_exist

        if DISABLE_VECTOR_DB:
            return False

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
                        SEMANTIC_QUERIES_FIELD: {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of natural-language semantic queries. Each should be "
                                "a complete, standalone, natural-language question — "
                                "typically very similar to the user's ask; do not simplify "
                                "or truncate."
                            ),
                        },
                        KEYWORD_QUERIES_FIELD: {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of keyword queries. Extract only the most relevant "
                                "keywords and create variations or expansions using "
                                "synonyms or other forms of the key terms."
                            ),
                        },
                    },
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

    @log_function_time(
        func_name="Search tool - automatic semantic rephrase",
        print_only=True,
        debug_only=True,
    )
    def _maybe_semantic_rephrase(
        self,
        skip_query_expansion: bool,
        override_kwargs: SearchToolOverrideKwargs,
    ) -> str | None:
        """Run the automatic semantic rephrase for the first search call of the
        turn. Computed at most once per turn (shared through the turn state, so
        parallel first-cycle calls reuse a single result); skipped entirely on
        repeat calls."""
        if skip_query_expansion:
            return None

        message_history = (
            override_kwargs.message_history if override_kwargs.message_history else []
        )
        if not message_history:
            return None
        memories = (
            override_kwargs.user_memory_context.as_formatted_list()
            if override_kwargs.user_memory_context
            else []
        )
        user_info = override_kwargs.user_info

        return self.turn_state.get_or_compute_rephrase(
            lambda: semantic_query_rephrase(
                message_history, self.llm, user_info, memories
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

        semantic_queries = _coerce_query_list(llm_kwargs.get(SEMANTIC_QUERIES_FIELD))
        keyword_queries = _coerce_query_list(llm_kwargs.get(KEYWORD_QUERIES_FIELD))
        if not semantic_queries and not keyword_queries:
            raise ToolCallException(
                message=(
                    "internal_search called without any semantic_queries or "
                    "keyword_queries"
                ),
                llm_facing_message=(
                    "The internal_search tool requires at least one of "
                    f"'{SEMANTIC_QUERIES_FIELD}' or '{KEYWORD_QUERIES_FIELD}' to be a "
                    "non-empty array of strings. Please provide the queries like: "
                    f'{{"{SEMANTIC_QUERIES_FIELD}": ["your standalone question here"], '
                    f'"{KEYWORD_QUERIES_FIELD}": ["relevant key terms"]}}'
                ),
            )

        # Pre-fetch all DB data in a single short-lived session so that
        # parallel search workers need zero DB connections.
        with get_session_with_current_tenant() as db_session:
            # ACL filters
            acl_filters: list[str] | None = (
                None
                if self.bypass_acl
                else build_access_filters_for_user(self.user, db_session)
            )

            # Validate document-set access for user-supplied filters.
            if (
                self.user_selected_filters
                and self.user_selected_filters.document_set
                and not self.bypass_acl
                and self.user
                and not self.user.is_anonymous
            ):
                requested = self.user_selected_filters.document_set
                accessible = filter_document_set_names_by_user_access(
                    db_session=db_session,
                    document_set_names=requested,
                    user=self.user,
                )
                unauthorized = sorted(
                    name for name in requested if name not in accessible
                )
                if unauthorized:
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        f"User does not have access to document sets: {unauthorized}",
                    )

            # SearchSettings → materialise EmbeddingModel while session is
            # open (forces lazy-load of cloud_provider properties)
            search_settings = get_current_search_settings(db_session)
            if not search_settings:
                raise RuntimeError(
                    "No search settings configured — cannot run internal search"
                )

            embedding_model = EmbeddingModel.from_db_model(
                search_settings=search_settings,
                server_host=MODEL_SERVER_HOST,
                server_port=MODEL_SERVER_PORT,
            )

            # Federated retrieval functions (non-Slack; Slack is separate)
            if self.project_id_filter is not None:
                # Project mode ignores user filters → no federated sources
                prefetch_source_types = None
            else:
                prefetch_source_types = (
                    list(self.user_selected_filters.source_type)
                    if self.user_selected_filters
                    and self.user_selected_filters.source_type
                    else None
                )
            federated_retrieval_infos = (
                get_federated_retrieval_functions(
                    db_session=db_session,
                    user_id=self.user.id if self.user else None,
                    source_types=prefetch_source_types,
                    document_set_names=self.persona_search_info.document_set_names,
                )
                or []
            )

            # Slack tokens and entity config — only prefetch when Slack
            # search is enabled or we're in a Slack bot context.
            if self.enable_slack_search or self.slack_context:
                slack_access_token, slack_bot_token, slack_entities = (
                    self._prefetch_slack_data(db_session)
                )
            else:
                slack_access_token, slack_bot_token, slack_entities = (
                    None,
                    None,
                    {},
                )
        # Session is closed here — all parallel work uses plain Python objects only

        # Automatic semantic rephrase — first search call of the turn only.
        automatic_semantic_expansion = self._maybe_semantic_rephrase(
            skip_query_expansion=override_kwargs.skip_query_expansion,
            override_kwargs=override_kwargs,
        )

        effective_filters = self.user_selected_filters

        # Prepare queries with their weights and hybrid_alpha settings
        # Group 1: Keyword queries — pure keyword (BM25) search, no embedding
        keyword_queries_with_weights = [
            (kw_query, MODEL_KEYWORD_QUERY_WEIGHT) for kw_query in keyword_queries
        ]
        deduplicated_keyword_queries = deduplicate_queries(keyword_queries_with_weights)

        # Group 2: Semantic/Original queries (use hybrid_alpha=None)
        semantic_queries_with_weights = (
            [
                (automatic_semantic_expansion, LLM_SEMANTIC_QUERY_WEIGHT),
            ]
            if automatic_semantic_expansion
            else []
        )
        for semantic_llm_query in semantic_queries:
            semantic_queries_with_weights.append(
                (semantic_llm_query, MODEL_SEMANTIC_QUERY_WEIGHT)
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
            "All Queries (sorted by weight): %s, Keyword queries: %s",
            all_queries,
            [q for q, _ in deduplicated_keyword_queries],
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

        # Run all searches in parallel. Semantic queries use the default hybrid
        # search; keyword queries run pure keyword (BM25) with no embedding.
        # The (query, weight, alpha) specs are also recorded on the search
        # entry so pagination can re-run the exact same document-index queries
        # with an offset. Slack federated search is excluded from those specs.
        search_functions: list[tuple[Callable, tuple]] = []
        search_weights: list[float] = []
        query_specs: list[ExecutedQuerySpec] = []

        for query, weight in deduplicated_semantic_queries:
            query_specs.append(
                ExecutedQuerySpec(query=query, weight=weight, hybrid_alpha=None)
            )
        for query, weight in deduplicated_keyword_queries:
            query_specs.append(
                ExecutedQuerySpec(
                    query=query, weight=weight, hybrid_alpha=KEYWORD_ONLY_HYBRID_ALPHA
                )
            )

        for spec in query_specs:
            search_functions.append(
                (
                    self._run_search_for_query,
                    (
                        spec.query,
                        spec.hybrid_alpha,
                        override_kwargs.num_hits,
                        acl_filters,
                        embedding_model,
                        federated_retrieval_infos,
                        effective_filters,
                    ),
                )
            )
            search_weights.append(spec.weight)

        # Add Slack federated search (runs once in parallel with all document
        # index queries). This avoids the query multiplication problem where
        # each query would trigger a separate Slack search.
        # Only run if pre-fetch found a valid Slack access token.
        if slack_access_token and override_kwargs.original_query:
            search_functions.append(
                (
                    self._run_slack_search,
                    (
                        override_kwargs.original_query,
                        slack_access_token,
                        slack_bot_token,
                        slack_entities,
                        search_settings,
                    ),
                )
            )
            # Use same weight as original query for Slack results
            search_weights.append(ORIGINAL_QUERY_WEIGHT)

        # Run all searches in parallel (document index queries + Slack)
        all_search_results = run_functions_tuples_in_parallel(search_functions)
        if not all_search_results:
            all_search_results = []

        # Merge results using weighted Reciprocal Rank Fusion
        # This intelligently combines rankings from different queries
        top_chunks = weighted_reciprocal_rank_fusion(
            ranked_results=all_search_results,
            weights=search_weights,
            id_extractor=lambda chunk: f"{chunk.document_id}_{chunk.chunk_id}",
        )

        # The window past num_hits is not returned now, but is cached on the
        # search entry so paginate_search_results can serve deeper pages.
        all_merged_sections = merge_individual_chunks(top_chunks)
        num_hits = override_kwargs.num_hits or NUM_RETURNED_HITS
        top_sections = all_merged_sections[:num_hits]

        secondary_flows_user_query = (
            override_kwargs.original_query
            or automatic_semantic_expansion
            or (semantic_queries[0] if semantic_queries else "")
            or (keyword_queries[0] if keyword_queries else "")
        )

        entry = SearchEntry(
            query_specs=query_specs,
            merged_sections=all_merged_sections,
            cached_chunk_ids={
                (chunk.document_id, chunk.chunk_id)
                for section in all_merged_sections
                for chunk in section.chunks
            },
            per_query_fetch_depth=num_hits,
            user_query=secondary_flows_user_query,
            effective_filters=effective_filters,
            acl_filters=acl_filters,
            embedding_model=embedding_model,
            project_id_filter=self.project_id_filter,
            persona_id_filter=self.persona_id_filter,
            bypass_acl=self.bypass_acl,
            exhausted=not top_sections,
        )
        search_query_id = self.turn_state.register(entry)

        if not top_sections:
            logger.info("Search tool - no results found, returning empty response")
            empty_response, _ = convert_inference_sections_to_llm_string(
                top_sections=[],
                search_query_id=search_query_id,
                automatic_semantic_expansion=automatic_semantic_expansion,
            )
            tool_response = ToolResponse(
                rich_response=SearchDocsResponse(
                    search_docs=[],
                    citation_mapping={},
                    displayed_docs=None,
                ),
                llm_facing_response=empty_response,
            )
            entry.page_responses[0] = tool_response
            return tool_response

        tool_response = run_post_retrieval_pipeline(
            sections=top_sections,
            user_query=secondary_flows_user_query,
            llm=self.llm,
            document_index=self.document_index,
            emitter=self.emitter,
            placement=placement,
            starting_citation_num=override_kwargs.starting_citation_num,
            max_llm_chunks=override_kwargs.max_llm_chunks,
            include_link=override_kwargs.include_link,
            search_query_id=search_query_id,
            automatic_semantic_expansion=automatic_semantic_expansion,
        )
        # Stash for idempotent re-serving via paginate_search_results page 0.
        entry.page_responses[0] = tool_response

        overall_elapsed = time.time() - overall_start_time
        logger.debug(
            "Search tool - Total execution time: %s seconds",
            format(overall_elapsed, ".3f"),
        )

        return tool_response
