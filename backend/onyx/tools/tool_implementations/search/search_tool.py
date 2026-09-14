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

import json
import re
import time
from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.configs.app_configs import OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
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
    SearchDocsResponse,
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
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.federated_connectors.federated_retrieval import (
    FederatedRetrievalInfo,
    get_federated_retrieval_functions,
)
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.onyxbot.slack.models import SlackContext
from onyx.secondary_llm_flows.document_filter import (
    select_chunks_for_relevance,
    select_sections_for_expansion,
)
from onyx.secondary_llm_flows.query_expansion import (
    keyword_query_expansion,
    semantic_query_rephrase,
)
from onyx.secondary_llm_flows.source_filter import SearchCycle, decide_search_scope
from onyx.secondary_llm_flows.time_filter import TimeFilter, decide_time_filter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    SearchToolDocumentsDelta,
    SearchToolFilterDelta,
    SearchToolQueriesDelta,
    SearchToolStart,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ChatMinimalTextMessage,
    SearchToolOverrideKwargs,
    ToolCallException,
    ToolResponse,
)
from onyx.tools.tool_implementations.search.adaptive_search import (
    decide_adaptive_search_next_queries,
    decide_answer_verification_next_queries,
    generate_search_answer_candidate,
)
from onyx.tools.tool_implementations.search.constants import (
    KEYWORD_QUERY_HYBRID_ALPHA,
    LLM_KEYWORD_QUERY_WEIGHT,
    LLM_NON_CUSTOM_QUERY_WEIGHT,
    LLM_SEMANTIC_QUERY_WEIGHT,
    MAX_CHUNKS_FOR_RELEVANCE,
    ORIGINAL_QUERY_WEIGHT,
)
from onyx.tools.tool_implementations.search.rerank_selection import (
    select_sections_with_cohere_rerank,
)
from onyx.tools.tool_implementations.search.search_utils import (
    document_level_reciprocal_rank_fusion,
    expand_section_with_context,
    merge_overlapping_sections,
    weighted_reciprocal_rank_fusion,
)
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time
from shared_configs.configs import (
    DOC_EMBEDDING_CONTEXT_SIZE,
    MODEL_SERVER_HOST,
    MODEL_SERVER_PORT,
)

logger = setup_logger()

QUERIES_FIELD = "queries"
_HI_TAG_PATTERN = re.compile(r"</?hi>", flags=re.IGNORECASE)


class QueryExpansionAndScope(BaseModel):
    """Result of one search cycle's query expansion + source-scope decision."""

    semantic_query: str | None
    keyword_queries: list[str]
    plan_scope: list[DocumentSource] | None
    time_filter: TimeFilter | None = None


def _expansion_history_with_objective(
    message_history: list[ChatMinimalTextMessage],
    queries: list[str],
) -> list[ChatMinimalTextMessage]:
    """Make the current search objective the query rewriter's final user message."""
    objective = next((query.strip() for query in queries if query.strip()), None)
    if objective is None:
        return message_history
    return [
        *message_history,
        ChatMinimalTextMessage(message=objective, message_type=MessageType.USER),
    ]


def _late_lexical_bridge_query(objective: str) -> str | None:
    objective_lower = objective.lower()
    concepts: list[tuple[tuple[str, ...], str]] = [
        (("partner integration", "integration call"), "marketplace integration sync"),
        (("cloud catalog", "pre-publication"), "marketplace listing"),
        (("image security", "security smoke"), "AMI security QA"),
        (("stop-and-go", "chat sessions"), "fractured context session anchoring"),
        (("per-session", "recent sessions"), "session anchors Redis hot LRU"),
        (("longer retention", "retention"), "S3 long-term TTL"),
        (("shared service", "hosted"), "Hosted API"),
        (("private network", "isolated deployment"), "Dedicated VPC"),
        (("assistant responses", "in app assistant"), "in-app help"),
        (("follow up actions", "action items"), "account plan action items POC"),
        (("product analytics",), "product analytics"),
        (
            ("cheaper", "consistent", "predictable latency"),
            "lower inference unit costs predictable latency",
        ),
    ]
    matches = [
        phrase
        for needles, phrase in concepts
        if any(needle in objective_lower for needle in needles)
    ]
    if len(matches) < 2:
        return None
    return " ".join(matches)


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


def _build_retrieval_candidate_diagnostics(
    *,
    query_specs: list[tuple[str, float, float | None]],
    round_search_weights: list[float],
    round_results: list[list[InferenceChunk]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for (query, _weight, hybrid_alpha), fusion_weight, chunks in zip(
        query_specs,
        round_search_weights,
        round_results,
        strict=True,
    ):
        diagnostics.append(
            {
                "query": query,
                "hybrid_alpha": hybrid_alpha,
                "fusion_weight": fusion_weight,
                "returned_chunks": [
                    _build_retrieval_candidate_chunk_diagnostics(
                        chunk=chunk,
                        rank=rank,
                    )
                    for rank, chunk in enumerate(chunks, start=1)
                ],
            }
        )
    return diagnostics


def _build_retrieval_candidate_chunk_diagnostics(
    *,
    chunk: InferenceChunk,
    rank: int,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "document_id": chunk.document_id,
        "chunk_id": chunk.chunk_id,
        "rank": rank,
    }
    # Bounded passages for inspecting already-authorized alternative candidates.
    # IDs/ranks cover the full returned window; text covers only its first eight hits.
    if rank <= 8:
        diagnostics.update(
            {
                "title": chunk.semantic_identifier,
                "content": chunk.content[:6000],
                "content_total_chars": len(chunk.content),
                "source_type": chunk.source_type.value,
                "indexed_updated_at": chunk.updated_at.isoformat()
                if chunk.updated_at
                else None,
            }
        )
    if chunk.score is not None:
        diagnostics["score"] = chunk.score
    return diagnostics


def _merged_candidate_document_ids_after_cap(
    sections: list[InferenceSection],
) -> list[str]:
    seen: set[str] = set()
    document_ids: list[str] = []
    for section in sections:
        document_id = section.center_chunk.document_id
        if document_id in seen:
            continue
        seen.add(document_id)
        document_ids.append(document_id)
    return document_ids


def _build_match_highlight_diagnostics(
    sections: list[InferenceSection],
) -> dict[str, int]:
    seen_chunk_ids: set[str] = set()
    chunks_with_match_highlights = 0
    tagged_fragments = 0

    for section in sections:
        for chunk in section.chunks:
            if chunk.unique_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.unique_id)

            if not chunk.match_highlights:
                continue
            chunks_with_match_highlights += 1
            tagged_fragments += sum(
                1
                for fragment in chunk.match_highlights
                if _HI_TAG_PATTERN.search(fragment)
            )

    return {
        "final_top_section_candidate_chunks_with_match_highlights": (
            chunks_with_match_highlights
        ),
        "final_top_section_tagged_match_highlight_fragments": tagged_fragments,
    }


def _convert_sections_to_llm_string_with_stable_citations(
    *,
    sections: list[InferenceSection],
    document_id_to_citation_id: dict[str, int],
    citation_start: int,
    limit: int | None,
    include_link: bool,
    note: str | None,
) -> tuple[str, dict[int, str]]:
    if limit is not None:
        sections = sections[:limit]

    next_citation_id = (
        max(document_id_to_citation_id.values()) + 1
        if document_id_to_citation_id
        else citation_start
    )
    for section in sections:
        document_id = section.center_chunk.document_id
        if document_id in document_id_to_citation_id:
            continue
        document_id_to_citation_id[document_id] = next_citation_id
        next_citation_id += 1

    results: list[dict[str, object]] = []
    citation_mapping: dict[int, str] = {}
    for section in sections:
        chunk = section.center_chunk
        document_id = chunk.document_id
        citation_id = document_id_to_citation_id[document_id]
        citation_mapping[citation_id] = document_id

        result: dict[str, object] = {
            "document": citation_id,
            "title": chunk.semantic_identifier,
            "source_type": chunk.source_type.value,
            "content": section.combined_content,
        }
        if chunk.updated_at is not None:
            result["updated_at"] = chunk.updated_at.isoformat()
        if include_link and chunk.source_links:
            link = next(iter(chunk.source_links.values()), None)
            if link:
                result["url"] = link
        if chunk.metadata:
            result["metadata"] = json.dumps(chunk.metadata, ensure_ascii=False)
        results.append(result)

    payload: dict[str, object] = {"results": results}
    if note:
        payload["note"] = note
    return json.dumps(payload, indent=2, ensure_ascii=False), citation_mapping


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


class SearchTool(Tool[SearchToolOverrideKwargs]):
    NAME = "internal_search"
    DISPLAY_NAME = "Internal Search"
    DESCRIPTION = "Search connected applications for information."

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
        # Whether to infer source and time filters from the
        # query. When False, only user/persona-selected filters are applied.
        auto_detect_filters: bool = True,
        classifier_llm: LLM | None = None,
        candidate_preparation: bool = False,
        hierarchical_selection: bool = False,
        final_selection_limit: int = 10,
        record_query: str | None = None,
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
        self.auto_detect_filters = auto_detect_filters
        self.classifier_llm = classifier_llm
        self.candidate_preparation = candidate_preparation
        self.hierarchical_selection = hierarchical_selection
        self.final_selection_limit = final_selection_limit
        self.record_query = record_query

        self._search_cycles: list[SearchCycle] = []
        self._cached_expansion: tuple[str | None, list[str]] | None = None
        self._scope_decision_settled = False
        self._time_filter: TimeFilter | None = None
        self._time_filter_computed = False

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
        func_name="Search tool - query expansion + scope decision",
        print_only=True,
        debug_only=True,
    )
    def _expand_queries_and_decide_scope(
        self,
        skip_query_expansion: bool,
        message_history: list[ChatMinimalTextMessage],
        user_info: str | None,
        memories: list[str],
        decide_args: tuple[Any, ...],
        queries: list[str] | None = None,
    ) -> QueryExpansionAndScope:
        """Expand the query and decide the source/time scope, in parallel when each
        applies.

        Repeat calls reuse the cached expansion instead of re-expanding. Once the
        scope decision finds no source directive it latches off for the rest of the
        turn, since the conversation cannot introduce one mid-turn. The time-window
        decision is computed once per turn and cached. Both auto decisions are
        gated by ``auto_detect_filters``.
        """
        expand_queries = not skip_query_expansion
        decide_scope = self.auto_detect_filters and not self._scope_decision_settled
        decide_time = self.auto_detect_filters and not self._time_filter_computed

        jobs: list[tuple[Callable, tuple]] = []
        scope_job_index: int | None = None
        time_job_index: int | None = None
        if expand_queries:
            expansion_history = _expansion_history_with_objective(
                message_history, queries or []
            )
            expansion_args = (expansion_history, self.llm, user_info, memories)
            jobs.append((semantic_query_rephrase, expansion_args))
            jobs.append((keyword_query_expansion, expansion_args))
        if decide_scope:
            scope_job_index = len(jobs)
            jobs.append((decide_search_scope, decide_args))
        if decide_time:
            time_job_index = len(jobs)
            jobs.append((decide_time_filter, (message_history, self.llm)))

        results = run_functions_tuples_in_parallel(jobs) if jobs else []

        semantic_query: str | None = None
        keyword_queries: list[str] = []
        if expand_queries:
            semantic_query = results[0]
            keyword_queries = results[1] or []
            self._cached_expansion = (semantic_query, keyword_queries)

        plan_scope: list[DocumentSource] | None = None
        if scope_job_index is not None:
            plan_scope = results[scope_job_index]
            self._scope_decision_settled = plan_scope is None

        if time_job_index is not None:
            self._time_filter = results[time_job_index]
            self._time_filter_computed = True

        return QueryExpansionAndScope(
            semantic_query=semantic_query,
            keyword_queries=keyword_queries,
            plan_scope=plan_scope,
            time_filter=self._time_filter,
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
        document_selection_elapsed = 0.0
        document_expansion_elapsed = 0.0

        connected_sources: list[DocumentSource] = []

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

            # Project mode ignores user filters, so source scoping doesn't apply.
            if self.project_id_filter is None:
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

        if QUERIES_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{QUERIES_FIELD}' parameter in internal_search tool call",
                llm_facing_message=(
                    f"The internal_search tool requires a '{QUERIES_FIELD}' parameter "
                    f"containing an array of search queries. Please provide the queries "
                    f'like: {{"queries": ["your search query here"]}}'
                ),
            )
        llm_queries = cast(list[str], llm_kwargs[QUERIES_FIELD])

        # Run semantic and keyword query expansion in parallel (unless skipped)
        # Use message history, memories, and user info from override_kwargs
        message_history = (
            override_kwargs.message_history if override_kwargs.message_history else []
        )
        memories = (
            override_kwargs.user_memory_context.as_formatted_list()
            if override_kwargs.user_memory_context
            else []
        )
        user_info = override_kwargs.user_info

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

        decide_args = (
            message_history,
            self.llm,
            candidate_sources,
            list(self._search_cycles),
            llm_queries,
        )
        expansion = self._expand_queries_and_decide_scope(
            skip_query_expansion=override_kwargs.skip_query_expansion
            or bool(self.record_query),
            message_history=message_history,
            queries=llm_queries,
            user_info=user_info,
            memories=memories,
            decide_args=decide_args,
        )
        semantic_query = expansion.semantic_query
        keyword_queries = expansion.keyword_queries
        plan_scope = expansion.plan_scope

        resolved_scope = (
            plan_scope if plan_scope is not None else user_source_restriction
        )

        logger.info(
            "Internal search - source scope: %s",
            [s.value for s in resolved_scope] if resolved_scope else "all sources",
        )

        # On a repeat call that advanced to a not-yet-searched source, reuse the
        # cached expansion (it is source-agnostic) rather than searching raw queries.
        searched_sources = {
            value for cycle in self._search_cycles for value in cycle.searched_sources
        }
        is_new_filter = bool(resolved_scope) and any(
            source.value not in searched_sources for source in resolved_scope
        )
        if (
            override_kwargs.skip_query_expansion
            and is_new_filter
            and self._cached_expansion is not None
        ):
            semantic_query, keyword_queries = self._cached_expansion

        self._search_cycles.append(
            SearchCycle(
                cycle_number=len(self._search_cycles) + 1,
                queries=list(llm_queries),
                searched_sources=(
                    [source.value for source in resolved_scope]
                    if resolved_scope
                    else []
                ),
            )
        )

        # Surface the applied filters (source scope + time window) to the UI. Scope
        # is reported only when it narrows to a strict subset — scoping to all
        # connected sources is equivalent to an unscoped search.
        scopes_all_sources = bool(connected_sources) and set(
            connected_sources
        ).issubset(resolved_scope or [])
        emitted_sources = (
            [source.value for source in resolved_scope]
            if resolved_scope and not scopes_all_sources
            else []
        )
        time_filter = expansion.time_filter
        if emitted_sources or time_filter is not None:
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=SearchToolFilterDelta(
                        sources=emitted_sources,
                        time_filter_start=time_filter.start if time_filter else None,
                        time_filter_end=time_filter.end if time_filter else None,
                    ),
                )
            )

        queries_run = list(
            dict.fromkeys(
                llm_queries
                + ([semantic_query] if semantic_query else [])
                + keyword_queries
            )
        )
        if self.record_query:
            queries_run = [self.record_query]
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
        if override_kwargs.original_query:
            semantic_queries_with_weights.append(
                (override_kwargs.original_query, ORIGINAL_QUERY_WEIGHT)
            )
        deduplicated_semantic_queries = deduplicate_queries(
            semantic_queries_with_weights
        )
        if self.record_query:
            # Preserve the caller's primary-record terms in one existing keyword
            # hybrid lane. Selection still uses the original task below.
            deduplicated_semantic_queries = []
            deduplicated_keyword_queries = [(self.record_query, 1.0)]

        # Build the all_queries list for UI display, sorted by weight (highest first)
        # Combine all deduplicated queries and sort by weight
        all_queries_with_weights = (
            deduplicated_semantic_queries + deduplicated_keyword_queries
        )
        all_queries_with_weights.sort(key=lambda x: x[1], reverse=True)

        answer_verification_config = override_kwargs.answer_verification
        adaptive_config = (
            None
            if answer_verification_config is not None
            else override_kwargs.adaptive_search
        )
        center_first_evidence = override_kwargs.center_first_evidence or (
            adaptive_config.center_first_evidence
            if adaptive_config is not None
            else False
        )
        loop_config = answer_verification_config or adaptive_config
        keyword_query_keys = {
            query.casefold() for query, _ in deduplicated_keyword_queries
        }

        # Extract queries in weight order, handling cross-duplicates
        all_query_specs: list[tuple[str, float, float | None]] = []
        seen_lower = set()
        for query, weight in all_queries_with_weights:
            query_lower = query.lower()
            if query_lower not in seen_lower:
                all_query_specs.append(
                    (
                        query,
                        weight,
                        (
                            KEYWORD_QUERY_HYBRID_ALPHA
                            if query.casefold() in keyword_query_keys
                            else None
                        ),
                    )
                )
                seen_lower.add(query_lower)

        display_query_specs = all_query_specs
        if loop_config is not None:
            display_query_specs = display_query_specs[: loop_config.max_total_queries]
        all_queries = [query for query, _, _ in display_query_specs]

        logger.debug(
            "All Queries (sorted by weight): %s, Keyword queries: %s",
            all_queries,
            [q for q, _ in deduplicated_keyword_queries],
        )

        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolQueriesDelta(
                    queries=all_queries,
                ),
            )
        )

        secondary_flows_user_query = (
            override_kwargs.original_query
            or semantic_query
            or (llm_queries[0] if llm_queries else "")
        )

        if loop_config is None:
            query_specs = [
                (query, weight, None) for query, weight in deduplicated_semantic_queries
            ]
            query_specs.extend(
                (query, weight, KEYWORD_QUERY_HYBRID_ALPHA)
                for query, weight in deduplicated_keyword_queries
            )
        else:
            query_specs = list(display_query_specs)

        searched_query_keys = {query.casefold() for query in all_queries}
        max_rounds = loop_config.max_rounds if loop_config else 1
        search_weights: list[float] = []
        all_search_results: list[list[InferenceChunk]] = []
        top_sections: list[InferenceSection] = []
        adaptive_stop_reason = "disabled"
        adaptive_rounds: list[dict[str, Any]] = []
        answer_verification_stop_reason = "disabled"
        answer_verification_rounds: list[dict[str, Any]] = []
        answer_verification_answer: str | None = None
        answer_verification_context: str | None = None
        answer_verification_citation_mapping: dict[int, str] = {}
        document_id_to_citation_id: dict[str, int] = {}
        selection_prompt_diagnostics: dict[str, Any] = {}
        hierarchical_selection_diagnostics: dict[str, Any] | None = None
        selection_stage_ids: dict[str, list[str]] = {}
        rerank_diagnostics: dict[str, Any] | None = None
        total_search_elapsed_ms = 0.0
        total_answer_synthesis_ms = 0.0
        total_answer_classifier_ms = 0.0
        include_retrieval_candidates = override_kwargs.include_retrieval_candidates

        for round_index in range(max_rounds):
            search_functions: list[tuple[Callable, tuple]] = []
            round_search_weights: list[float] = []
            round_query_specs: list[tuple[str, float, float | None]] = []
            for query, weight, hybrid_alpha in query_specs:
                search_functions.append(
                    (
                        self._run_search_for_query,
                        (
                            query,
                            hybrid_alpha,
                            override_kwargs.num_hits,
                            acl_filters,
                            embedding_model,
                            federated_retrieval_infos,
                            effective_filters,
                        ),
                    )
                )
                round_search_weights.append(weight)
                round_query_specs.append((query, weight, hybrid_alpha))

            if (
                round_index == 0
                and slack_access_token
                and override_kwargs.original_query
            ):
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
                round_search_weights.append(ORIGINAL_QUERY_WEIGHT)
                round_query_specs.append(
                    (
                        override_kwargs.original_query,
                        ORIGINAL_QUERY_WEIGHT,
                        None,
                    )
                )

            search_start = time.time()
            round_results = run_functions_tuples_in_parallel(search_functions)
            search_elapsed_ms = round((time.time() - search_start) * 1000, 3)
            total_search_elapsed_ms += search_elapsed_ms
            if round_results:
                all_search_results.extend(round_results)
                search_weights.extend(round_search_weights)

            if all_search_results:
                if override_kwargs.fusion_granularity == "document":
                    top_chunks = document_level_reciprocal_rank_fusion(
                        ranked_results=all_search_results,
                        weights=search_weights,
                    )
                else:
                    top_chunks = weighted_reciprocal_rank_fusion(
                        ranked_results=all_search_results,
                        weights=search_weights,
                        id_extractor=lambda chunk: chunk.unique_id,
                    )
                merged_candidates = merge_individual_chunks(top_chunks)
                if self.candidate_preparation:
                    from onyx.tools.tool_implementations.search.candidate_preparation import (
                        distinct_document_sections,
                    )

                    top_sections = distinct_document_sections(merged_candidates)
                else:
                    top_sections = merged_candidates[: override_kwargs.num_hits]

            round_diagnostics: dict[str, Any] = {
                "round": round_index + 1,
                "queries": [query for query, _, _ in query_specs],
                "search_elapsed_ms": search_elapsed_ms,
                "candidate_section_count": len(top_sections),
            }
            if include_retrieval_candidates:
                round_diagnostics["retrieval_candidates"] = (
                    _build_retrieval_candidate_diagnostics(
                        query_specs=round_query_specs,
                        round_search_weights=round_search_weights,
                        round_results=round_results,
                    )
                )
                round_diagnostics["merged_candidate_document_ids_after_cap"] = (
                    _merged_candidate_document_ids_after_cap(top_sections)
                )

            adaptive_rounds.append(round_diagnostics)
            if answer_verification_config is not None:
                answer_verification_context, answer_verification_citation_mapping = (
                    _convert_sections_to_llm_string_with_stable_citations(
                        sections=top_sections,
                        document_id_to_citation_id=document_id_to_citation_id,
                        citation_start=override_kwargs.starting_citation_num,
                        limit=override_kwargs.max_llm_chunks,
                        include_link=override_kwargs.include_link,
                        note=scope_note or None,
                    )
                )
                synthesis_start = time.time()
                answer_verification_answer = generate_search_answer_candidate(
                    question=secondary_flows_user_query,
                    search_context=answer_verification_context,
                    llm=self.llm,
                    max_tokens=answer_verification_config.max_answer_tokens,
                    reasoning_effort=(
                        answer_verification_config.synthesis_reasoning_effort
                    ),
                )
                synthesis_elapsed_ms = round((time.time() - synthesis_start) * 1000, 3)
                total_answer_synthesis_ms += synthesis_elapsed_ms

                round_diagnostics: dict[str, Any] = {
                    "round": round_index + 1,
                    "queries": [query for query, _, _ in query_specs],
                    "search_elapsed_ms": search_elapsed_ms,
                    "synthesis_elapsed_ms": synthesis_elapsed_ms,
                    "classifier_elapsed_ms": 0.0,
                    "candidate_section_count": len(top_sections),
                    "accepted": False,
                }
                if include_retrieval_candidates:
                    round_diagnostics["retrieval_candidates"] = (
                        _build_retrieval_candidate_diagnostics(
                            query_specs=round_query_specs,
                            round_search_weights=round_search_weights,
                            round_results=round_results,
                        )
                    )
                    round_diagnostics["merged_candidate_document_ids_after_cap"] = (
                        _merged_candidate_document_ids_after_cap(top_sections)
                    )
                query_specs = []

                remaining_total_queries = (
                    answer_verification_config.max_total_queries - len(all_queries)
                )
                can_search_again = (
                    round_index + 1 < answer_verification_config.max_rounds
                    and remaining_total_queries > 0
                )

                classifier_start = time.time()
                verification_decision = decide_answer_verification_next_queries(
                    question=secondary_flows_user_query,
                    search_context=answer_verification_context,
                    candidate_answer=answer_verification_answer,
                    max_tokens=answer_verification_config.max_classifier_tokens,
                    prior_queries=all_queries,
                    llm=self.classifier_llm or self.llm,
                    max_queries=min(
                        answer_verification_config.max_refinement_queries_per_round,
                        remaining_total_queries if can_search_again else 0,
                    ),
                )
                classifier_elapsed_ms = round(
                    (time.time() - classifier_start) * 1000, 3
                )
                total_answer_classifier_ms += classifier_elapsed_ms
                round_diagnostics["classifier_elapsed_ms"] = classifier_elapsed_ms

                if verification_decision.accept is True:
                    answer_verification_stop_reason = (
                        verification_decision.reason or "answer_verified"
                    )
                    round_diagnostics["accepted"] = True
                    round_diagnostics["decision"] = {
                        "accept": True,
                        "reason": answer_verification_stop_reason,
                        "refined_queries": [],
                    }
                    answer_verification_rounds.append(round_diagnostics)
                    break
                if verification_decision.accept is None:
                    answer_verification_stop_reason = (
                        verification_decision.reason or "verification_unknown"
                    )
                    round_diagnostics["decision"] = {
                        "accept": None,
                        "reason": answer_verification_stop_reason,
                        "refined_queries": [],
                    }
                    answer_verification_rounds.append(round_diagnostics)
                    break

                if not can_search_again:
                    answer_verification_stop_reason = (
                        "max_rounds"
                        if round_index + 1 >= answer_verification_config.max_rounds
                        else "query_budget_exhausted"
                    )
                    round_diagnostics["decision"] = {
                        "accept": False,
                        "reason": answer_verification_stop_reason,
                        "refined_queries": [],
                    }
                    answer_verification_rounds.append(round_diagnostics)
                    break

                refined_queries = [
                    query
                    for query in verification_decision.refined_queries
                    if query.casefold() not in searched_query_keys
                ][:remaining_total_queries]
                round_diagnostics["decision"] = {
                    "accept": False,
                    "reason": verification_decision.reason,
                    "refined_queries": refined_queries,
                }
                answer_verification_rounds.append(round_diagnostics)
                if not refined_queries:
                    answer_verification_stop_reason = "no_new_queries"
                    break

                for query in refined_queries:
                    searched_query_keys.add(query.casefold())
                    all_queries.append(query)
                query_specs = [
                    (
                        query,
                        LLM_NON_CUSTOM_QUERY_WEIGHT,
                        answer_verification_config.refinement_hybrid_alpha,
                    )
                    for query in refined_queries
                ]
                answer_verification_stop_reason = (
                    verification_decision.reason or "refined"
                )
                self.emitter.emit(
                    Packet(
                        placement=placement,
                        obj=SearchToolQueriesDelta(
                            queries=all_queries,
                        ),
                    )
                )
                continue
            query_specs = []
            if adaptive_config is None:
                break
            if round_index + 1 >= adaptive_config.max_rounds:
                adaptive_stop_reason = "max_rounds"
                break

            remaining_total_queries = adaptive_config.max_total_queries - len(
                all_queries
            )
            if remaining_total_queries <= 0:
                adaptive_stop_reason = "query_budget_exhausted"
                break

            decision = decide_adaptive_search_next_queries(
                question=secondary_flows_user_query,
                sections=top_sections,
                prior_queries=all_queries,
                balanced_evidence_preview=adaptive_config.balanced_evidence_preview,
                center_first_evidence=center_first_evidence,
                llm=self.llm,
                max_queries=min(
                    adaptive_config.max_refinement_queries_per_round,
                    remaining_total_queries,
                ),
            )
            if decision.sufficient is True:
                adaptive_stop_reason = decision.reason or "evidence_sufficient"
                adaptive_rounds[-1]["decision"] = {
                    "sufficient": decision.sufficient,
                    "reason": adaptive_stop_reason,
                    "refined_queries": [],
                }
                break
            if decision.sufficient is None:
                adaptive_stop_reason = decision.reason or "decision_unknown"
                adaptive_rounds[-1]["decision"] = {
                    "sufficient": None,
                    "reason": adaptive_stop_reason,
                    "refined_queries": [],
                }
                break

            refined_queries = [
                query
                for query in decision.refined_queries
                if query.casefold() not in searched_query_keys
            ][:remaining_total_queries]
            adaptive_rounds[-1]["decision"] = {
                "sufficient": decision.sufficient,
                "reason": decision.reason,
                "refined_queries": refined_queries,
            }
            if not refined_queries:
                adaptive_stop_reason = "no_new_queries"
                break

            for query in refined_queries:
                searched_query_keys.add(query.casefold())
                all_queries.append(query)
            query_specs = [
                (
                    query,
                    LLM_NON_CUSTOM_QUERY_WEIGHT,
                    adaptive_config.refinement_hybrid_alpha,
                )
                for query in refined_queries
            ]
            adaptive_stop_reason = decision.reason or "refined"
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=SearchToolQueriesDelta(
                        queries=all_queries,
                    ),
                )
            )

        expansion_fallbacks: list[bool] = []
        expansion_not_relevant: list[str] = []

        def build_search_tool_diagnostics() -> dict[str, Any]:
            retrieval_diagnostics: dict[str, Any] = {
                "mode": (
                    "answer_verification"
                    if answer_verification_config is not None
                    else "adaptive"
                    if adaptive_config is not None
                    else "fixed"
                ),
                "query_count": len(all_queries),
                "elapsed_ms": round(total_search_elapsed_ms, 3),
                "candidate_section_count": len(top_sections),
                "requested_num_hits": override_kwargs.num_hits,
                "selection_stage_document_ids": selection_stage_ids,
                "candidate_preparation": selection_prompt_diagnostics,
                "hierarchical_selection": hierarchical_selection_diagnostics,
                "selection_strategy": override_kwargs.selection_strategy,
                "fusion_granularity": override_kwargs.fusion_granularity,
                "opensearch_match_highlights_disabled": (
                    OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED
                ),
                **_build_match_highlight_diagnostics(top_sections),
            }
            if rerank_diagnostics is not None:
                retrieval_diagnostics["rerank"] = rerank_diagnostics
            if (
                include_retrieval_candidates
                and answer_verification_config is None
                and adaptive_config is None
                and adaptive_rounds
            ):
                first_round = adaptive_rounds[0]
                retrieval_diagnostics["retrieval_candidates"] = first_round.get(
                    "retrieval_candidates", []
                )
                retrieval_diagnostics["merged_candidate_document_ids_after_cap"] = (
                    first_round.get("merged_candidate_document_ids_after_cap", [])
                )

            diagnostics = {
                "context_expansion": {
                    "fallback_count": len(expansion_fallbacks),
                    "not_relevant_retained_document_ids": sorted(
                        set(expansion_not_relevant)
                    ),
                },
                "retrieval": retrieval_diagnostics,
                "adaptive_search": {
                    "enabled": adaptive_config is not None,
                    "stop_reason": adaptive_stop_reason,
                    "rounds": adaptive_rounds,
                    "queries": all_queries,
                },
                "answer_verification": {
                    "enabled": False,
                },
            }
            if answer_verification_config is None:
                return diagnostics

            diagnostics["answer_verification"] = {
                "enabled": True,
                "stop_reason": answer_verification_stop_reason,
                "rounds": answer_verification_rounds,
                "queries": all_queries,
                "total_synthesis_ms": round(total_answer_synthesis_ms, 3),
                "total_classifier_ms": round(total_answer_classifier_ms, 3),
                "synthesis_reasoning_effort": (
                    answer_verification_config.synthesis_reasoning_effort.value
                ),
                "classifier_reasoning_effort": "off",
                "classifier_model": (
                    self.classifier_llm.config.model_name
                    if self.classifier_llm is not None
                    else self.llm.config.model_name
                ),
            }
            return diagnostics

        if answer_verification_config is not None:
            answer_docs = convert_inference_sections_to_search_docs(
                top_sections, is_internet=False
            )
            evidence_doc_ids = set(answer_verification_citation_mapping.values())
            displayed_answer_docs = [
                document
                for document in answer_docs
                if document.document_id in evidence_doc_ids
            ]
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=SearchToolDocumentsDelta(documents=displayed_answer_docs),
                )
            )
            return ToolResponse(
                rich_response=SearchDocsResponse(
                    search_docs=answer_docs,
                    displayed_docs=displayed_answer_docs,
                    citation_mapping=answer_verification_citation_mapping,
                    answer=answer_verification_answer,
                    search_tool_diagnostics=build_search_tool_diagnostics(),
                ),
                llm_facing_response=answer_verification_answer or "",
            )

        if not top_sections:
            if override_kwargs.selection_strategy == "cohere_rerank":
                _empty_sections, rerank_diagnostics = (
                    select_sections_with_cohere_rerank(
                        query=secondary_flows_user_query,
                        sections=[],
                        embedding_model=embedding_model,
                        include_candidate_scores=include_retrieval_candidates,
                        top_n=override_kwargs.rerank_top_n,
                    )
                )
            logger.info("Search tool - no results found, returning empty response")
            empty_response, _ = convert_inference_sections_to_llm_string(
                top_sections=[],
                note=scope_note or None,
            )
            llm_facing_response = (
                answer_verification_answer
                if answer_verification_config is not None
                and answer_verification_answer is not None
                else empty_response
            )
            return ToolResponse(
                rich_response=SearchDocsResponse(
                    search_docs=[],
                    citation_mapping={},
                    answer=answer_verification_answer,
                    search_tool_diagnostics=build_search_tool_diagnostics(),
                    displayed_docs=None,
                ),
                llm_facing_response=llm_facing_response,
            )

        # Enrich chunks with `Document.file_id` (Postgres-only metadata not
        # stored in Vespa).
        with get_session_with_current_tenant() as enrichment_session:
            populate_file_ids_on_sections(top_sections, enrichment_session)

        # Convert InferenceSections to SearchDocs for emission
        search_docs = convert_inference_sections_to_search_docs(
            top_sections, is_internet=False
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
        sections_for_selection = (
            top_sections
            if self.candidate_preparation or override_kwargs.balanced_selection
            else _trim_sections_by_tokens(
                sections=top_sections,
                max_tokens=max_tokens_for_selection,
                token_counter=token_counter,
                max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
            )
        )

        if include_retrieval_candidates:
            selection_stage_ids["selection_input"] = (
                _merged_candidate_document_ids_after_cap(sections_for_selection)
            )

        # Start timing for LLM document selection
        document_selection_start_time = time.time()

        if self.hierarchical_selection:
            from onyx.tools.tool_implementations.search.hierarchical_selection import (
                select_hierarchically,
            )

            selected_sections, best_doc_ids, hierarchical_selection_diagnostics = (
                select_hierarchically(
                    ranked_results=all_search_results,
                    user_query=secondary_flows_user_query,
                    llm=self.llm,
                    document_index=self.document_index,
                    final_limit=self.final_selection_limit,
                )
            )
            if include_retrieval_candidates:
                selection_stage_ids["selection_input"] = (
                    hierarchical_selection_diagnostics["nominee_document_ids"]
                )
        elif override_kwargs.selection_strategy == "cohere_rerank":
            selected_sections, rerank_diagnostics = select_sections_with_cohere_rerank(
                query=secondary_flows_user_query,
                sections=sections_for_selection,
                embedding_model=embedding_model,
                include_candidate_scores=include_retrieval_candidates,
                top_n=override_kwargs.rerank_top_n,
            )
            best_doc_ids = None
        else:
            # Use LLM to select the most relevant sections for expansion
            selected_sections, best_doc_ids = select_sections_for_expansion(
                sections=sections_for_selection,
                user_query=secondary_flows_user_query,
                llm=self.llm,
                max_chunks_per_section=MAX_CHUNKS_FOR_RELEVANCE,
                max_content_chars=(
                    max(1, max_tokens_for_selection * 4 // len(top_sections))
                    if override_kwargs.balanced_selection
                    and not self.candidate_preparation
                    else None
                ),
                center_first_evidence=center_first_evidence,
                use_query_highlights=override_kwargs.selection_query_highlights,
                input_token_budget=min(16384, max_tokens_for_selection)
                if self.candidate_preparation
                else None,
                preparation_diagnostics=selection_prompt_diagnostics
                if self.candidate_preparation
                else None,
            )

        if include_retrieval_candidates:
            selection_stage_ids["selected"] = _merged_candidate_document_ids_after_cap(
                selected_sections
            )

        if (
            self.candidate_preparation
            and "included_section_ids" in selection_prompt_diagnostics
        ):
            selection_stage_ids["selection_input"] = (
                _merged_candidate_document_ids_after_cap(
                    [
                        sections_for_selection[i]
                        for i in selection_prompt_diagnostics["included_section_ids"]
                    ]
                )
            )

        # End timing for LLM document selection
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
            context_expansion_strategy: Literal["llm", "adjacent_2"],
        ) -> InferenceSection:
            """Wrapper that handles exceptions and returns original section on error."""
            try:
                expanded_section = expand_section_with_context(
                    section=section,
                    user_query=user_query,
                    llm=llm,
                    document_index=document_index,
                    expand_override=expand_override,
                    context_expansion_strategy=context_expansion_strategy,
                )
                # Return expanded section if not None, otherwise original
                if expanded_section is None:
                    expansion_not_relevant.append(section.center_chunk.document_id)
                return expanded_section if expanded_section is not None else section
            except Exception as e:
                expansion_fallbacks.append(True)
                logger.warning(
                    "Error processing section context expansion: %s. Using original section.",
                    e,
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
                    override_kwargs.context_expansion_strategy,
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
            "Search tool - Expansion of selected documents took %s seconds (expanded %s sections)",
            format(document_expansion_elapsed, ".3f"),
            len(expanded_sections),
        )

        if not expanded_sections:
            expanded_sections = selected_sections

        # Merge sections from the same document that have adjacent or overlapping chunks
        # This prevents duplicate content and reduces token usage
        merged_sections = merge_overlapping_sections(expanded_sections)

        adaptive_note = (
            f"Adaptive internal search stop reason: {adaptive_stop_reason}. "
            f"Queries run: {'; '.join(all_queries)}."
            if adaptive_config is not None
            else None
        )
        response_note = "\n".join(
            note for note in [scope_note or None, adaptive_note] if note
        )

        docs_str, citation_mapping = convert_inference_sections_to_llm_string(
            top_sections=merged_sections,
            citation_start=override_kwargs.starting_citation_num,
            limit=override_kwargs.max_llm_chunks,
            include_document_id=False,
            include_link=override_kwargs.include_link,
            note=response_note or None,
        )

        # End overall timing
        overall_elapsed = time.time() - overall_start_time
        logger.debug(
            "Search tool - Total execution time: %s seconds (document selection: %ss, document expansion: %ss)",
            format(overall_elapsed, ".3f"),
            format(document_selection_elapsed, ".3f"),
            format(document_expansion_elapsed, ".3f"),
        )

        if include_retrieval_candidates:
            selection_stage_ids["expanded"] = _merged_candidate_document_ids_after_cap(
                merged_sections
            )
            selection_stage_ids["returned_evidence"] = list(
                dict.fromkeys(citation_mapping.values())
            )
        llm_facing_response = docs_str

        return ToolResponse(
            # Typically the rich response will give more docs in case it needs to be displayed in the UI
            rich_response=SearchDocsResponse(
                search_docs=search_docs,
                citation_mapping=citation_mapping,
                answer=answer_verification_answer,
                search_tool_diagnostics=build_search_tool_diagnostics(),
                displayed_docs=final_ui_docs,
            ),
            # The LLM facing response typically includes less docs to cut down on noise and token usage
            llm_facing_response=llm_facing_response,
        )
