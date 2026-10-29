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
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

from sqlalchemy.orm import Session

from onyx.agents.tools import (
    ToolInvocation,
    ToolProgress,
    ToolUpdate,
)
from onyx.chat.incognito import current_turn_persists_content
from onyx.configs.chat_configs import (
    ENABLE_SEARCH_DECISION_RERANK_EXPANSION,
    MAX_CHUNKS_FED_TO_CHAT,
    NUM_RETURNED_HITS,
)
from onyx.configs.constants import DocumentSource, FederatedConnectorSource, MessageType
from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import (
    BaseFilters,
    ChunkIndexRequest,
    ChunkSearchRequest,
    IndexFilters,
    InferenceChunk,
    InferenceSection,
    PersonaSearchInfo,
    SearchCycle,
    SearchDocsResponse,
    UserAccessFilters,
)
from onyx.context.search.pipeline import merge_individual_chunks, search_pipeline
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import (
    convert_inference_sections_to_search_docs,
    populate_file_ids_on_sections,
)
from onyx.db.connector import (
    check_connectors_exist,
    check_federated_connectors_exist,
    fetch_unique_document_sources,
)
from onyx.db.document_set import filter_document_set_names_by_user_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.federated import (
    get_federated_connector_document_set_mappings_by_document_set_names,
    list_federated_connector_oauth_tokens,
)
from onyx.db.models import SearchSettings, User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.slack_bot import fetch_slack_bots
from onyx.document_index.interfaces import DocumentIndex
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.federated_connectors.federated_retrieval import (
    FederatedRetrievalInfo,
    get_federated_retrieval_functions,
)
from onyx.llm.decisions.client import DecisionClient
from onyx.llm.factory import get_decision_client, get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolDefinition, ToolResult, ToolResultMessage
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.onyxbot.slack.models import SlackContext
from onyx.secondary_llm_flows.decision_rerank_expansion import (
    MAX_DECISION_QUESTIONS,
    rank_sections_listwise,
)
from onyx.secondary_llm_flows.document_filter import (
    select_chunks_for_relevance,
    select_sections_for_expansion,
)
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.secondary_llm_flows.source_filter import decide_search_scope
from onyx.secondary_llm_flows.time_filter import decide_time_filter
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import INTERNAL_SEARCH_TOOL_NAME
from onyx.tools.interface import (
    CITATIONS_PER_TOOL_CALL,
    Tool,
    parse_tool_arguments,
    tool_message_history,
)
from onyx.tools.models import (
    ChatMinimalTextMessage,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.search.constants import (
    DECISION_TIMEOUT_S,
    KEYWORD_QUERY_HYBRID_ALPHA,
    LLM_KEYWORD_QUERY_WEIGHT,
    LLM_NON_CUSTOM_QUERY_WEIGHT,
    LLM_SEMANTIC_QUERY_WEIGHT,
    MAX_CHUNKS_FOR_RELEVANCE,
    MAX_SELECTED_SECTIONS,
    ORIGINAL_QUERY_WEIGHT,
    RERANK_POOL_SIZE,
    RERANK_SPECULATIVE_EXPANSIONS,
    RERANK_TOKEN_BUDGET_MULTIPLIER,
    SELECTION_TOKEN_BUDGET_MULTIPLIER,
)
from onyx.tools.tool_implementations.search.models import (
    QueryExpansionAndScope,
    SearchArguments,
    SearchContext,
    SearchPlanningResult,
)
from onyx.tools.tool_implementations.search.search_utils import (
    expand_section_with_context,
    merge_overlapping_sections,
    weighted_reciprocal_rank_fusion,
)
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import (
    run_functions_tuples_in_parallel,
    run_in_background,
    wait_on_background,
)
from onyx.utils.timing import log_function_time
from shared_configs.configs import (
    DOC_EMBEDDING_CONTEXT_SIZE,
    MODEL_SERVER_HOST,
    MODEL_SERVER_PORT,
)
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# PostHog flag for decision-model rerank and expansion (cloud rollout control).
SEARCH_DECISION_RERANK_EXPANSION_FLAG = "onyx-search-decision-rerank-expansion"

QUERIES_FIELD = "queries"


def update_search_context(
    context: SearchContext, results: Sequence[ToolResultMessage]
) -> SearchContext:
    """Fold completed searches in model-call order, counting merged retrievals once."""
    new_cycles: list[SearchCycle] = []
    cached_expansion = context.cached_expansion
    scope_decision_settled = context.scope_decision_settled
    time_filter = context.time_filter
    time_filter_computed = context.time_filter_computed
    seen_calls: set[str] = set()
    for result in results:
        planning = result.metadata
        if result.is_error or not isinstance(planning, SearchPlanningResult):
            continue
        if planning.tool_call_id is not None:
            if planning.tool_call_id in seen_calls:
                continue
            seen_calls.add(planning.tool_call_id)
        new_cycles.append(
            SearchCycle(
                cycle_number=len(context.search_cycles) + len(new_cycles) + 1,
                queries=list(planning.original_queries),
                searched_sources=list(planning.searched_sources),
            )
        )
        if planning.cached_expansion is not None:
            cached_expansion = planning.cached_expansion
        scope_decision_settled |= planning.scope_decision_settled
        if planning.time_filter_computed and not time_filter_computed:
            time_filter = planning.time_filter
            time_filter_computed = True
    if not new_cycles:
        return context
    return SearchContext(
        search_cycles=context.search_cycles + tuple(new_cycles),
        cached_expansion=cached_expansion,
        scope_decision_settled=scope_decision_settled,
        time_filter=time_filter,
        time_filter_computed=time_filter_computed,
    )


def _build_scope_note(
    scope: list[DocumentSource] | None, queries_run: list[str]
) -> str:
    """Note appended to a scoped search's response: which source(s) it covered
    and the queries that ran, so a repeat can vary terms. "" when unscoped."""
    if not scope:
        return ""
    searched = ", ".join(source.value for source in scope)
    queries_str = "; ".join(queries_run) or "(none)"
    return (
        f"(This internal search covered only: {searched}. Queries run: {queries_str}. "
        "Call internal_search again with different query terms to keep searching.)"
    )


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


@log_function_time()
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


class SearchTool(Tool):
    merge_list_argument = QUERIES_FIELD

    NAME = INTERNAL_SEARCH_TOOL_NAME
    DISPLAY_NAME = "Internal Search"
    DESCRIPTION = "Search connected applications for information."

    def __init__(
        self,
        tool_id: int,
        # Used for ACLs and federated search, anonymous users only see public docs
        user: User,
        # Pre-extracted persona search configuration
        persona_search_info: PersonaSearchInfo,
        llm: LLM,
        document_index: DocumentIndex,
        # Respecting user selections
        user_selected_filters: BaseFilters | None,
        # Document index metadata filters for overflowing user files.  NOT the raw IDs
        # of the current project/persona — only set when user files couldn't
        # fit in the LLM context and need to be searched via vector DB.
        project_id_filter: int | None,
        persona_id_filter: int | None = None,
        # Slack context for federated Slack search (tokens fetched internally)
        slack_context: SlackContext | None = None,
        # Whether to enable Slack federated search
        enable_slack_search: bool = True,
        # Whether to infer source and time filters from the
        # query. When False, only user/persona-selected filters are applied.
        auto_detect_filters: bool = True,
        selection_llm_factory: Callable[[], LLM] | None = None,
        primary_llm_cost_checked: bool = True,
        include_link: bool = False,
    ) -> None:

        self.user = user
        self.persona_search_info = persona_search_info
        self.llm = llm
        self._selection_llm_factory = selection_llm_factory
        self._primary_llm_cost_checked = primary_llm_cost_checked
        self.document_index = document_index
        self.user_selected_filters = user_selected_filters
        self.project_id_filter = project_id_filter
        self.persona_id_filter = persona_id_filter
        self.slack_context = slack_context
        self.enable_slack_search = enable_slack_search
        self.auto_detect_filters = auto_detect_filters
        self.include_link = include_link

        self._id = tool_id

    def _resolve_decision_client(self) -> DecisionClient | None:
        """The decision model client when the rollout flag is on, the turn
        persists content, and a default decision model is configured;
        otherwise None."""
        flag_provider = get_default_feature_flag_provider()
        if isinstance(flag_provider, NoOpFeatureFlagProvider):
            enabled = ENABLE_SEARCH_DECISION_RERANK_EXPANSION
        else:
            enabled = flag_provider.feature_enabled_for_user_tenant(
                SEARCH_DECISION_RERANK_EXPANSION_FLAG,
                self.user,
                get_current_tenant_id(),
            )
        # The decision client carries no incognito request policy, so turns
        # that must not persist content keep LLM selection.
        if not enabled or not current_turn_persists_content():
            return None
        try:
            return get_decision_client(timeout=DECISION_TIMEOUT_S)
        except Exception:
            logger.warning(
                "Decision model unavailable, using LLM selection", exc_info=True
            )
            return None

    @staticmethod
    def _select_with_decision_model(
        candidates: list[InferenceSection],
        user_query: str,
        decision_client: DecisionClient,
        max_tokens: int,
        token_counter: Callable[[str], int],
        expand: Callable[[InferenceSection], InferenceSection],
    ) -> tuple[list[InferenceSection], dict[int, InferenceSection]] | None:
        """Rank the candidates in one decision call and keep the top sections.

        The fused top sections are expanded in the background while the call
        runs; only selected sections are waited on. Returns the selected
        sections and the expansions already done, keyed by section id, or None
        when the ranking call fails."""
        pool = _trim_sections_by_tokens(
            sections=candidates,
            max_tokens=max_tokens,
            token_counter=token_counter,
            max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
        )[:MAX_DECISION_QUESTIONS]
        speculative = [
            (section, run_in_background(expand, section))
            for section in pool[:RERANK_SPECULATIVE_EXPANSIONS]
        ]
        try:
            scores = rank_sections_listwise(pool, user_query, decision_client)
        except Exception:
            # Unselected background expansions finish on their own; nothing waits.
            logger.warning(
                "Decision-model rerank failed, using LLM selection", exc_info=True
            )
            return None
        # A stable sort keeps fusion order among equal probabilities.
        ranked = sorted(zip(pool, scores, strict=True), key=lambda item: -item[1])
        selected = [section for section, _ in ranked[:MAX_SELECTED_SECTIONS]]
        selected_ids = {id(section) for section in selected}
        expanded = {
            id(section): wait_on_background(task)
            for section, task in speculative
            if id(section) in selected_ids
        }
        return selected, expanded

    @property
    def _is_project_only_search(self) -> bool:
        return self.project_id_filter is not None and self.persona_id_filter is None

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
                llm=self.llm,
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
        acl_filters: UserAccessFilters,
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
            acl_filters: Pre-fetched ACL filters for the acting user
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
                # Project-only searches ignore user-selected filters.
                user_selected_filters=(
                    effective_filters if not self._is_project_only_search else None
                ),
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

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    QUERIES_FIELD: {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of search queries to execute, typically a single query. "
                            "Query expansion and filter extraction steps will be run "
                            "automatically downstream, do not include time or source type "
                            "scoping details in your query."
                        ),
                    },
                },
                "required": [QUERIES_FIELD],
            },
        )

    @log_function_time(
        func_name="Search tool - query expansion + scope decision",
        debug_only=True,
    )
    def _expand_queries_and_decide_scope(
        self,
        skip_query_expansion: bool,
        search_context: SearchContext,
        message_history: list[ChatMinimalTextMessage],
        user_info: str | None,
        memories: list[str],
        candidate_sources: list[DocumentSource],
        llm_queries: list[str],
    ) -> QueryExpansionAndScope:
        """Infer missing search decisions from the prior completed-step context."""
        expand_queries = not skip_query_expansion
        decide_scope = (
            self.auto_detect_filters and not search_context.scope_decision_settled
        )
        decide_time = (
            self.auto_detect_filters and not search_context.time_filter_computed
        )

        jobs: list[tuple[Callable, tuple]] = []
        scope_job_index: int | None = None
        time_job_index: int | None = None
        if expand_queries:
            expansion_args = (
                message_history,
                self.llm,
                user_info,
                memories,
            )
            jobs.append((semantic_query_rephrase, expansion_args))
            jobs.append((keyword_query_expansion, expansion_args))
        if decide_scope:
            scope_job_index = len(jobs)
            jobs.append(
                (
                    decide_search_scope,
                    (
                        message_history,
                        self.llm,
                        candidate_sources,
                        list(search_context.search_cycles),
                        llm_queries,
                    ),
                )
            )
        if decide_time:
            time_job_index = len(jobs)
            jobs.append(
                (
                    decide_time_filter,
                    (message_history, self.llm),
                )
            )

        results = run_functions_tuples_in_parallel(jobs) if jobs else []

        semantic_query: str | None = None
        keyword_queries: list[str] = []
        if expand_queries:
            semantic_query = results[0]
            keyword_queries = results[1] or []

        plan_scope: list[DocumentSource] | None = None
        if scope_job_index is not None:
            plan_scope = results[scope_job_index]

        return QueryExpansionAndScope(
            semantic_query=semantic_query,
            keyword_queries=keyword_queries,
            plan_scope=plan_scope,
            scope_decision_settled=decide_scope and plan_scope is None,
            time_filter=(
                results[time_job_index]
                if time_job_index is not None
                else search_context.time_filter
            ),
            time_filter_computed=decide_time,
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        message_history = tool_message_history(list(invocation.messages))
        original_query = next(
            (
                message.message
                for message in reversed(message_history)
                if message.message_type == MessageType.USER
            ),
            None,
        )
        if original_query is None:
            raise ValueError("Search requires a user message")
        if QUERIES_FIELD not in invocation.arguments:
            raise ToolCallException(
                message=f"Missing required '{QUERIES_FIELD}' parameter in internal_search tool call",
                llm_facing_message=(
                    f"The internal_search tool requires a '{QUERIES_FIELD}' parameter "
                    f"containing an array of search queries. Please provide the queries "
                    f'like: {{"queries": ["your search query here"]}}'
                ),
            )
        llm_queries = parse_tool_arguments(
            SearchArguments, invocation.arguments
        ).queries

        return self.search(
            llm_queries,
            original_query=original_query,
            message_history=message_history,
            context=context,
            citation_start=context.next_citation_num
            + CITATIONS_PER_TOOL_CALL * invocation.call_index,
            update=invocation.update,
            tool_call_id=invocation.call_id,
        )

    @log_function_time()
    def search(
        self,
        llm_queries: list[str],
        *,
        original_query: str,
        message_history: list[ChatMinimalTextMessage],
        context: ToolContext,
        citation_start: int = 1,
        update: ToolUpdate | None = None,
        tool_call_id: str | None = None,
    ) -> ToolResult:
        """Retrieve documents using the original question and optional query variants."""
        # An explicitly empty source selection is a statement, not an absent
        # filter: the tool still runs (it may be forced), and it honestly
        # finds nothing. `None` keeps its meaning of "no source filter".
        # Project-only searches ignore user filters, so the guard must too.
        if (
            self.user_selected_filters is not None
            and not self._is_project_only_search
            and self.user_selected_filters.source_type == []
        ):
            content, _ = convert_inference_sections_to_llm_string(
                top_sections=[], note=None
            )
            return ToolResult(
                content=content,
                details=SearchDocsResponse(search_docs=[], citation_mapping={}),
            )
        memory = context.user_memory_context
        if memory is not None and not context.inject_memories_in_prompt:
            memory = memory.without_memories()
        search_output = SearchDocsResponse(
            search_docs=[], citation_mapping={}, queries=list(llm_queries)
        )
        overall_start_time = time.time()

        # Initialize timing variables (in case of early exceptions)
        document_selection_elapsed = 0.0
        document_expansion_elapsed = 0.0

        connected_sources: list[DocumentSource] = []

        # Pre-fetch all DB data in a single short-lived session so that
        # parallel search workers need zero DB connections.
        with get_session_with_current_tenant() as db_session:
            # ACL filters
            acl_filters: UserAccessFilters = build_access_filters_for_user(
                self.user, db_session
            )

            # Validate document-set access for user-supplied filters.
            if (
                self.user_selected_filters
                and self.user_selected_filters.document_set
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
            if self._is_project_only_search:
                # Project-only searches ignore source selections.
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

            # Custom agents retain source selection inside projects.
            if not self._is_project_only_search:
                connected_sources = fetch_unique_document_sources(db_session)

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

        # Run semantic and keyword query expansion in parallel (unless skipped)
        memories = memory.as_formatted_list() if memory else []
        user_info = context.user_info

        # A persona/user source restriction is the outer bound the decision works within.
        user_source_restriction: list[DocumentSource] | None = (
            list(self.user_selected_filters.source_type)
            if self.user_selected_filters and self.user_selected_filters.source_type
            else None
        )
        if user_source_restriction is not None:
            allowed = set(user_source_restriction)
            candidate_sources = [s for s in connected_sources if s in allowed]
        else:
            candidate_sources = connected_sources

        expansion = self._expand_queries_and_decide_scope(
            skip_query_expansion=context.skip_search_query_expansion,
            search_context=context.search_context,
            message_history=message_history,
            user_info=user_info,
            memories=memories,
            candidate_sources=candidate_sources,
            llm_queries=llm_queries,
        )
        semantic_query = expansion.semantic_query
        keyword_queries = expansion.keyword_queries
        plan_scope = expansion.plan_scope

        resolved_scope = (
            plan_scope if plan_scope is not None else user_source_restriction
        )
        # Inferred connector sources must not hide files supplied as context.
        # Explicit source selections remain the outer bound.
        if (
            plan_scope is not None
            and (
                self.project_id_filter is not None or self.persona_id_filter is not None
            )
            and (
                user_source_restriction is None
                or DocumentSource.USER_FILE in user_source_restriction
            )
            and DocumentSource.USER_FILE not in plan_scope
        ):
            resolved_scope = [*plan_scope, DocumentSource.USER_FILE]

        logger.info(
            "Internal search - source scope: %s",
            [s.value for s in resolved_scope] if resolved_scope else "all sources",
        )

        # On a repeat call that advanced to a not-yet-searched source, reuse the
        # cached expansion (it is source-agnostic) rather than searching raw queries.
        searched_sources = {
            value
            for cycle in context.search_context.search_cycles
            for value in cycle.searched_sources
        }
        is_new_filter = bool(resolved_scope) and any(
            source.value not in searched_sources for source in resolved_scope
        )
        if (
            context.skip_search_query_expansion
            and is_new_filter
            and context.search_context.cached_expansion is not None
        ):
            semantic_query, cached_keywords = context.search_context.cached_expansion
            keyword_queries = list(cached_keywords)

        planning_result = SearchPlanningResult(
            tool_call_id=tool_call_id,
            original_queries=tuple(llm_queries),
            searched_sources=tuple(source.value for source in resolved_scope or ()),
            cached_expansion=(
                (expansion.semantic_query, tuple(expansion.keyword_queries))
                if not context.skip_search_query_expansion
                else None
            ),
            scope_decision_settled=expansion.scope_decision_settled,
            time_filter=(
                expansion.time_filter if expansion.time_filter_computed else None
            ),
            time_filter_computed=expansion.time_filter_computed,
        )

        # Scoping to all connected sources is equivalent to an unscoped search.
        scopes_all_sources = bool(connected_sources) and set(
            connected_sources
        ).issubset(resolved_scope or [])
        emitted_sources = (
            [source.value for source in resolved_scope]
            if resolved_scope and not scopes_all_sources
            else []
        )
        time_filter = expansion.time_filter
        search_output.sources = emitted_sources
        search_output.time_filter_start = time_filter.start if time_filter else None
        search_output.time_filter_end = time_filter.end if time_filter else None
        if update is not None:
            update(ToolProgress(details=search_output))

        queries_run = list(
            dict.fromkeys(
                llm_queries
                + ([semantic_query] if semantic_query else [])
                + keyword_queries
            )
        )
        scope_note = _build_scope_note(resolved_scope, queries_run)

        effective_filters = self.user_selected_filters
        if resolved_scope is not None:
            effective_filters = (
                self.user_selected_filters or BaseFilters()
            ).model_copy(update={"source_type": resolved_scope})
            federated_retrieval_infos = [
                info
                for info in federated_retrieval_infos
                if info.source.to_non_federated_source() in resolved_scope
            ]
            # Disable the Slack federated search when Slack is out of scope.
            if DocumentSource.SLACK not in resolved_scope:
                slack_access_token = None

        # The pipeline composes the lower bound with any persona time floor.
        if time_filter is not None:
            effective_filters = time_filter.apply_to(effective_filters or BaseFilters())
            logger.info(
                "Internal search - time window (%s): %s to %s",
                time_filter.field.value,
                time_filter.start.isoformat() if time_filter.start else "any",
                time_filter.end.isoformat() if time_filter.end else "any",
            )

        # Prepare queries with their weights and hybrid_alpha settings
        # Group 1: Keyword queries (use hybrid_alpha=0.2)
        keyword_queries_with_weights = [
            (kw_query, LLM_KEYWORD_QUERY_WEIGHT) for kw_query in keyword_queries
        ]
        deduplicated_keyword_queries = deduplicate_queries(keyword_queries_with_weights)

        # Group 2: Semantic/LLM/Original queries (use hybrid_alpha=None)
        # Include all LLM-provided queries with their weight
        semantic_queries_with_weights = (
            [
                (semantic_query, LLM_SEMANTIC_QUERY_WEIGHT),
            ]
            if semantic_query
            else []
        )
        # In rare cases, the LLM may fail to provide real queries
        semantic_queries_with_weights.extend(
            (llm_query, LLM_NON_CUSTOM_QUERY_WEIGHT)
            for llm_query in llm_queries
            if llm_query
        )
        if original_query:
            semantic_queries_with_weights.append(
                (original_query, ORIGINAL_QUERY_WEIGHT)
            )
        deduplicated_semantic_queries = deduplicate_queries(
            semantic_queries_with_weights
        )

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

        search_output.queries = all_queries
        if update is not None:
            update(ToolProgress(details=search_output))

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
                    (
                        query,
                        None,
                        NUM_RETURNED_HITS,
                        acl_filters,
                        embedding_model,
                        federated_retrieval_infos,
                        effective_filters,
                    ),
                )
            )
            search_weights.append(weight)

        # Add deduplicated keyword queries (use hybrid_alpha=0.2)
        for query, weight in deduplicated_keyword_queries:
            search_functions.append(
                (
                    self._run_search_for_query,
                    (
                        query,
                        KEYWORD_QUERY_HYBRID_ALPHA,
                        NUM_RETURNED_HITS,
                        acl_filters,
                        embedding_model,
                        federated_retrieval_infos,
                        effective_filters,
                    ),
                )
            )
            search_weights.append(weight)

        # Add Slack federated search (runs once in parallel with all index queries)
        # This avoids the query multiplication problem where each index query
        # would trigger a separate Slack search.
        # Only run if pre-fetch found a valid Slack access token.
        primary_llm_cost_checked = self._primary_llm_cost_checked

        def check_primary_llm_cost() -> None:
            nonlocal primary_llm_cost_checked
            if primary_llm_cost_checked:
                return
            with get_session_with_current_tenant() as usage_session:
                check_llm_cost_limit_for_provider(
                    db_session=usage_session,
                    tenant_id=get_current_tenant_id(),
                    llm_provider_api_key=self.llm.config.api_key,
                )
            primary_llm_cost_checked = True

        run_slack_search = bool(slack_access_token and original_query)
        if run_slack_search:
            try:
                check_primary_llm_cost()
            except Exception:
                logger.warning(
                    "Skipping Slack search: primary model cost check failed",
                    exc_info=True,
                )
                run_slack_search = False
        if run_slack_search:
            search_functions.append(
                (
                    self._run_slack_search,
                    (
                        original_query,
                        slack_access_token,
                        slack_bot_token,
                        slack_entities,
                        search_settings,
                    ),
                )
            )
            # Use same weight as original query for Slack results
            search_weights.append(ORIGINAL_QUERY_WEIGHT)

        # Run all searches in parallel (index queries + Slack)
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

        # We can disregard all of the chunks that exceed the num_hits parameter since it's not valid to have
        # documents/contents from things that aren't returned to the user on the frontend
        all_sections = merge_individual_chunks(top_chunks)
        top_sections = all_sections[:NUM_RETURNED_HITS]

        if not top_sections:
            logger.info("Search tool - no results found, returning empty response")
            empty_response, _ = convert_inference_sections_to_llm_string(
                top_sections=[],
                note=scope_note or None,
            )
            return ToolResult(
                details=SearchDocsResponse(
                    queries=search_output.queries,
                    sources=search_output.sources,
                    time_filter_start=search_output.time_filter_start,
                    time_filter_end=search_output.time_filter_end,
                    search_docs=[],
                    citation_mapping={},
                    displayed_docs=None,
                ),
                content=empty_response,
                metadata=planning_result,
            )

        selection_llm = self.llm
        if self._selection_llm_factory is not None:
            try:
                selection_llm = self._selection_llm_factory()
            except Exception:
                logger.warning(
                    "Search selection model unavailable, using the primary model",
                    exc_info=True,
                )
        if selection_llm is self.llm:
            check_primary_llm_cost()
        enforce_selection_input_budget = selection_llm is not self.llm

        decision_client = self._resolve_decision_client()
        # The decision model ranks a wider pool than the sections shown today.
        candidates = (
            all_sections[:RERANK_POOL_SIZE] if decision_client else top_sections
        )

        # Enrich chunks with `Document.file_id` (Postgres-only metadata not
        # stored in the document index).
        with get_session_with_current_tenant() as enrichment_session:
            populate_file_ids_on_sections(
                all_sections[: max(len(top_sections), len(candidates))],
                enrichment_session,
            )

        # Convert InferenceSections to SearchDocs for emission
        search_docs = convert_inference_sections_to_search_docs(
            top_sections, is_internet=False
        )

        secondary_flows_user_query = (
            original_query or semantic_query or (llm_queries[0] if llm_queries else "")
        )

        token_counter = get_llm_token_counter(self.llm)

        # Trim sections to fit within token budget before LLM selection
        # This is to account for very short chunks flooding the search context
        # Only consider MAX_CHUNKS_FOR_RELEVANCE chunks per section to avoid flooding from
        # documents with many matching sections
        max_tokens_for_selection = (
            MAX_CHUNKS_FED_TO_CHAT
            * DOC_EMBEDDING_CONTEXT_SIZE
            * SELECTION_TOKEN_BUDGET_MULTIPLIER
        )

        # This is approximate since it doesn't build the exact string of the call below
        # Some things are estimated and may be under (like the metadata tokens)
        sections_for_selection = _trim_sections_by_tokens(
            sections=top_sections,
            max_tokens=max_tokens_for_selection,
            token_counter=token_counter,
            max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
        )

        # Create wrapper function to handle errors gracefully
        def expand_section_safe(
            section: InferenceSection,
            user_query: str,
            llm: LLM,
            document_index: DocumentIndex,
            expand_override: bool,
            expansion_decision_client: DecisionClient | None,
        ) -> InferenceSection:
            """Wrapper that handles exceptions and returns original section on error."""
            try:
                expanded_section = expand_section_with_context(
                    section=section,
                    user_query=user_query,
                    llm=llm,
                    document_index=document_index,
                    expand_override=expand_override,
                    enforce_llm_input_budget=enforce_selection_input_budget,
                    decision_client=expansion_decision_client,
                )
                # Return expanded section if not None, otherwise original
                return expanded_section if expanded_section is not None else section
            except Exception as e:
                logger.warning(
                    "Error processing section context expansion: %s. Using original section.",
                    e,
                )
                return section

        # Start timing for LLM document selection
        document_selection_start_time = time.time()

        decided = (
            self._select_with_decision_model(
                candidates=candidates,
                user_query=secondary_flows_user_query,
                decision_client=decision_client,
                max_tokens=max_tokens_for_selection * RERANK_TOKEN_BUDGET_MULTIPLIER,
                token_counter=token_counter,
                expand=partial(
                    expand_section_safe,
                    user_query=secondary_flows_user_query,
                    llm=selection_llm,
                    document_index=self.document_index,
                    expand_override=False,
                    expansion_decision_client=decision_client,
                ),
            )
            if decision_client
            else None
        )
        pre_expanded: dict[int, InferenceSection] = {}
        if decided is not None:
            selected_sections, pre_expanded = decided
            best_doc_ids = None
            # Picks from beyond the top hits still need a search doc.
            top_section_ids = {id(section) for section in top_sections}
            search_docs += convert_inference_sections_to_search_docs(
                [s for s in selected_sections if id(s) not in top_section_ids],
                is_internet=False,
            )
        else:
            # The decision model failed or is off; it should not slow expansion.
            decision_client = None
            # Use LLM to select the most relevant sections for expansion
            selected_sections, best_doc_ids = select_sections_for_expansion(
                sections=sections_for_selection,
                user_query=secondary_flows_user_query,
                llm=selection_llm,
                max_sections=MAX_SELECTED_SECTIONS,
                max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
                enforce_llm_input_budget=enforce_selection_input_budget,
            )

        # End timing for LLM document selection
        document_selection_elapsed = time.time() - document_selection_start_time
        logger.debug(
            "Search tool - picking documents took %s seconds (selected %s sections, decision model: %s)",
            format(document_selection_elapsed, ".3f"),
            len(selected_sections),
            decided is not None,
        )

        # Create a set of best document IDs for quick lookup
        best_doc_ids_set = set(best_doc_ids) if best_doc_ids else set()

        # To show the users, we only pass in the docs that are determined to be good by the LLM
        final_ui_docs = convert_inference_sections_to_search_docs(
            selected_sections, is_internet=False
        )
        search_output.search_docs = search_docs
        search_output.displayed_docs = final_ui_docs
        if update is not None:
            update(ToolProgress(details=search_output))

        # Build parallel function calls for all sections
        expansion_functions: list[tuple[Callable, tuple]] = [
            (
                expand_section_safe,
                (
                    section,
                    secondary_flows_user_query,
                    selection_llm,
                    self.document_index,
                    section.center_chunk.document_id in best_doc_ids_set,
                    decision_client,
                ),
            )
            for section in selected_sections
            if id(section) not in pre_expanded
        ]

        # Start timing for document expansion
        document_expansion_start_time = time.time()

        # Run all expansions in parallel
        expanded_by_id = dict(pre_expanded)
        for (_, args), expanded in zip(
            expansion_functions,
            run_functions_tuples_in_parallel(expansion_functions),
            strict=True,
        ):
            expanded_by_id[id(args[0])] = expanded
        expanded_sections = [expanded_by_id[id(s)] for s in selected_sections]

        # End timing for document expansion
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
            citation_start=citation_start,
            limit=MAX_CHUNKS_FED_TO_CHAT,
            include_document_id=False,
            include_link=self.include_link,
            note=scope_note or None,
        )

        # End overall timing
        overall_elapsed = time.time() - overall_start_time
        logger.debug(
            "Search tool - Total execution time: %s seconds (document selection: %ss, document expansion: %ss)",
            format(overall_elapsed, ".3f"),
            format(document_selection_elapsed, ".3f"),
            format(document_expansion_elapsed, ".3f"),
        )

        return ToolResult(
            # Displayed documents can exceed the subset sent to the model.
            details=SearchDocsResponse(
                queries=search_output.queries,
                sources=search_output.sources,
                time_filter_start=search_output.time_filter_start,
                time_filter_end=search_output.time_filter_end,
                search_docs=search_docs,
                citation_mapping=citation_mapping,
                displayed_docs=final_ui_docs,
            ),
            content=docs_str,
            metadata=planning_result,
        )
