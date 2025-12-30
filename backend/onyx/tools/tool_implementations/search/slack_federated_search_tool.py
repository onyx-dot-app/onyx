"""
SlackFederatedSearchTool: A dedicated tool for Slack federated search.

WHY THIS TOOL EXISTS:
=====================
This tool was created to solve a query multiplication problem that caused excessive
Slack API calls and thread pool consumption.

PREVIOUS PROBLEM:
When Slack federated search was integrated into the main SearchTool pipeline:
1. SearchTool generates 8 query variations (semantic, keyword, original, etc.)
2. Each query independently flows to the search_pipeline
3. Each search_pipeline call triggers federated retrieval, including Slack
4. slack_retrieval does LLM-based query expansion (up to MAX_SLACK_QUERY_EXPANSIONS queries)
5. Result: 8 × 5 = 40+ Slack API calls per user message, causing:
   - Thread pool exhaustion
   - Rate limiting issues
   - Poor response times

SOLUTION:
This dedicated SlackFederatedSearchTool:
1. Runs in parallel with SearchTool at the tool_runner level (not through it)
2. Uses build_slack_queries() ONCE for LLM-based query expansion
3. Calls slack_retrieval() directly with the expanded queries
4. Result: Only 3-5 Slack API calls per user message

SearchTool no longer triggers Slack federated search through search_pipeline,
ensuring Slack is only searched through this dedicated tool.

This tool works for BOTH:
1. Slack bot context (when slack_context is present)
2. Web users with Slack federated OAuth tokens (when slack_context is None)
"""

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.chat.emitter import Emitter
from onyx.context.search.federated.slack_search import slack_retrieval
from onyx.context.search.models import ChunkIndexRequest
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.interface import Tool
from onyx.tools.models import SlackFederatedSearchToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _convert_chunks_to_search_docs(chunks: list[InferenceChunk]) -> list[SearchDoc]:
    """Convert InferenceChunks to SearchDocs for UI display."""
    search_docs: list[SearchDoc] = []
    seen_doc_ids: set[str] = set()

    for chunk in chunks:
        # Deduplicate by document_id
        if chunk.document_id in seen_doc_ids:
            continue
        seen_doc_ids.add(chunk.document_id)

        search_docs.append(
            SearchDoc(
                document_id=chunk.document_id,
                chunk_ind=chunk.chunk_id,
                semantic_identifier=chunk.semantic_identifier or "",
                link=chunk.source_links[0] if chunk.source_links else None,
                blurb=chunk.blurb,
                source_type=chunk.source_type,
                boost=chunk.boost,
                hidden=chunk.hidden,
                metadata=chunk.metadata,
                score=chunk.score,
                match_highlights=chunk.match_highlights,
                updated_at=chunk.updated_at,
                primary_owners=chunk.primary_owners,
                secondary_owners=chunk.secondary_owners,
                is_internet=False,
            )
        )

    return search_docs


class SlackFederatedSearchTool(Tool[SlackFederatedSearchToolOverrideKwargs]):
    """
    Dedicated tool for Slack federated search that runs in parallel with SearchTool.

    This tool exists to prevent query multiplication issues where SearchTool's
    8 query variations would each trigger independent Slack searches, causing
    40+ API calls. By running as a separate tool, we ensure Slack is searched
    exactly once with LLM-optimized queries.
    """

    NAME = "slack_federated_search"
    DISPLAY_NAME = "Slack Search"
    DESCRIPTION = "Search Slack messages and conversations."

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
        user: User | None,
        persona: Persona,
        # Slack bot context (optional - None for web users with OAuth)
        slack_context: SlackContext | None = None,
        # Bot token for enhanced permissions
        bot_token: str | None = None,
        # User/bot access token for API calls
        access_token: str | None = None,
        # Team ID for Slack workspace
        team_id: str | None = None,
        # Entity config for channel filtering
        entities: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(emitter=emitter)

        self.user = user
        self.persona = persona
        # slack_context is optional - None for web users with Slack OAuth
        self.slack_context = slack_context
        self.bot_token = bot_token
        self.access_token = access_token
        self.team_id = team_id
        self.entities = entities or {}

        # Store session factory for thread-safety
        self._session_bind = db_session.get_bind()
        self._session_factory = sessionmaker(bind=self._session_bind)

        self._id = tool_id

    def _get_thread_safe_session(self) -> Session:
        """Create a new database session for the current thread."""
        return self._session_factory()

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

    def tool_definition(self) -> dict:
        """Tool definition for LLM function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query for Slack messages",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        """Emit start packet for this tool."""
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolStart(),
            )
        )

    def run(
        self,
        placement: Placement,
        override_kwargs: SlackFederatedSearchToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """
        Execute Slack federated search.

        This method:
        1. Creates a ChunkIndexRequest from the query
        2. Calls slack_retrieval() which internally uses build_slack_queries()
           for LLM-based query expansion and date extraction
        3. Returns results formatted for the chat pipeline

        The build_slack_queries() function handles:
        - LLM-based query expansion (up to MAX_SLACK_QUERY_EXPANSIONS queries)
        - Date range extraction from natural language ("last week", "yesterday")
        - Channel reference detection and validation
        """
        self.emit_start(placement)

        # Get query from LLM kwargs or override
        query = llm_kwargs.get("query", override_kwargs.query)

        if not query:
            logger.warning("SlackFederatedSearchTool called without query")
            return ToolResponse(
                rich_response=SearchDocsResponse(search_docs=[], citation_mapping={}),
                llm_facing_response="No query provided for Slack search.",
            )

        if not self.access_token:
            logger.warning("SlackFederatedSearchTool called without access_token")
            return ToolResponse(
                rich_response=SearchDocsResponse(search_docs=[], citation_mapping={}),
                llm_facing_response="Slack search is not configured.",
            )

        db_session = self._get_thread_safe_session()
        try:
            # Create the query request object with minimal filters
            # (slack_retrieval only uses query.query, filters are not used)
            chunk_request = ChunkIndexRequest(
                query=query,
                filters=IndexFilters(access_control_list=None),
            )

            # Call slack_retrieval which handles:
            # - LLM query expansion via build_slack_queries()
            # - Date range extraction
            # - Channel filtering based on entities
            # - Parallel Slack API calls
            chunks = slack_retrieval(
                query=chunk_request,
                access_token=self.access_token,
                db_session=db_session,
                connector=None,  # Not used, kept for backwards compat
                entities=self.entities,
                limit=None,  # Let slack_retrieval use its own limits
                slack_event_context=self.slack_context,
                bot_token=self.bot_token,
                team_id=self.team_id,
            )

            logger.info(
                f"SlackFederatedSearchTool returned {len(chunks)} chunks for query: {query}"
            )

            # Convert chunks to search docs for UI
            search_docs = _convert_chunks_to_search_docs(chunks)

            # Emit documents to UI
            self.emitter.emit(
                Packet(
                    placement=placement,
                    obj=SearchToolDocumentsDelta(documents=search_docs),
                )
            )

            # Convert to LLM-facing string
            sections = [
                InferenceSection(
                    center_chunk=chunk,
                    chunks=[chunk],
                    combined_content=chunk.content,
                )
                for chunk in chunks
            ]

            docs_str, citation_mapping = convert_inference_sections_to_llm_string(
                top_sections=sections,
                citation_start=override_kwargs.starting_citation_num,
                limit=override_kwargs.max_llm_chunks,
            )

            return ToolResponse(
                rich_response=SearchDocsResponse(
                    search_docs=search_docs, citation_mapping=citation_mapping
                ),
                llm_facing_response=docs_str,
            )

        except Exception as e:
            logger.error(f"SlackFederatedSearchTool error: {e}", exc_info=True)
            return ToolResponse(
                rich_response=SearchDocsResponse(search_docs=[], citation_mapping={}),
                llm_facing_response=f"Error searching Slack: {str(e)}",
            )

        finally:
            db_session.close()
