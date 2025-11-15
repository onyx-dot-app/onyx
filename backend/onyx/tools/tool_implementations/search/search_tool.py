import json
from typing import Any
from typing import cast

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDoc
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.connector import check_connectors_exist
from onyx.db.connector import check_federated_connectors_exist
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import SearchToolRunContext
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()

SEARCH_EVALUATION_ID = "llm_doc_eval"
QUERY_FIELD = "query"


def _convert_search_docs_to_llm_string(
    top_sections: list[InferenceSection],
    citation_start: int = 1,
    limit: int | None = None,
) -> str:
    """Convert a list of InferenceSection objects to a JSON string for LLM consumption.

    Args:
        top_sections: List of InferenceSection objects to convert (contains full combined content)
        citation_start: Starting citation number (default: 1)
        limit: Maximum number of sections to include (None for no limit)

    Returns:
        JSON string with the structure:
        {
            "results": [
                {
                    "citation_id": int,
                    "title": str,  # semantic_identifier
                    "content": str,  # combined_content (full content)
                    "source_type": str,
                    "authors": list[str] | None,
                    "updated_at": str | None,  # ISO format
                    "metadata": str  # JSON string
                }
            ]
        }
    """
    # Apply limit if specified
    if limit is not None:
        top_sections = top_sections[:limit]

    results = []

    for idx, section in enumerate(top_sections):
        chunk = section.center_chunk

        # Combine primary and secondary owners for authors
        authors = None
        if chunk.primary_owners or chunk.secondary_owners:
            authors = []
            if chunk.primary_owners:
                authors.extend(chunk.primary_owners)
            if chunk.secondary_owners:
                authors.extend(chunk.secondary_owners)

        # Format updated_at as ISO string if available
        updated_at_str = None
        if chunk.updated_at:
            updated_at_str = chunk.updated_at.isoformat()

        # Convert metadata to JSON string
        metadata_str = json.dumps(chunk.metadata)

        result = {
            "citation_id": citation_start + idx,
            "title": chunk.semantic_identifier,
            "content": section.combined_content,
            "source_type": str(chunk.source_type),
            "authors": authors,
            "updated_at": updated_at_str,
            "metadata": metadata_str,
        }
        results.append(result)

    return json.dumps({"results": results}, indent=4)


SEARCH_TOOL_DESCRIPTION = """
Use the `internal_search` tool to search connected applications for information. Use `internal_search` when:
- Internal information: any time where there may be some information stored in internal applications that could help better \
answer the query.
- Niche/Specific information: information that is likely not found in public sources, things specific to a project or product, \
team, process, etc.
- Keyword Queries: queries that are heavily keyword based are often internal document search queries.
- Ambiguity: questions about something that is not widely known or understood.
Between internal and web search, think about if the user's query is likely better answered by team internal sources or online \
web pages. If very ambiguious, prioritize internal search or call both tools.
"""


class SearchTool(Tool[SearchToolOverrideKwargs, SearchToolRunContext]):
    _NAME = "internal_search"
    _DISPLAY_NAME = "Internal Search"
    _DESCRIPTION = SEARCH_TOOL_DESCRIPTION

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        # Used for ACLs and federated search
        user: User | None,
        # Used for filter settings
        persona: Persona,
        llm: LLM,
        fast_llm: LLM,
        document_index: DocumentIndex,
        # Respecting user selections
        user_selected_filters: BaseFilters | None,
        # If the chat is part of a project
        project_id: int | None,
        bypass_acl: bool = False,
        # Needed to help the Slack Federated search
        slack_context: SlackContext | None = None,
    ) -> None:
        self.user = user
        self.persona = persona
        self.llm = llm
        self.fast_llm = fast_llm
        self.document_index = document_index
        self.user_selected_filters = user_selected_filters
        self.project_id = project_id
        self.bypass_acl = bypass_acl
        self.slack_context = slack_context

        # Store session factory instead of session for thread-safety
        # When tools are called in parallel, each thread needs its own session
        # TODO ensure this works!!!
        self._session_bind = db_session.get_bind()
        self._session_factory = sessionmaker(bind=self._session_bind)

        self._id = tool_id

    def _get_thread_safe_session(self) -> Session:
        """Create a new database session for the current thread.

        This ensures thread-safety when the search tool is called in parallel.
        Each parallel execution gets its own isolated database session with
        its own transaction scope.

        Returns:
            A new SQLAlchemy Session instance
        """
        return self._session_factory()

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Check if search tool is available by verifying connectors exist."""
        return check_connectors_exist(db_session) or check_federated_connectors_exist(
            db_session
        )

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

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
                        QUERY_FIELD: {
                            "type": "string",
                            "description": "What to search for",
                        },
                    },
                    "required": [QUERY_FIELD],
                },
            },
        }

    def run(
        self,
        run_context: SearchToolRunContext,
        turn_index: int,
        tab_index: int,
        override_kwargs: SearchToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        # Create a new thread-safe session for this execution
        # This prevents transaction conflicts when multiple search tools run in parallel
        db_session = self._get_thread_safe_session()
        try:
            query = cast(str, llm_kwargs[QUERY_FIELD])

            # TODO this should be also passed in the history up to this point.

            # TODO use the original query.
            override_kwargs.original_query

            # Emit SearchToolStart packet at the beginning
            run_context.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    tab_index=tab_index,
                    obj=SearchToolStart(),
                )
            )

            # Emit the queries early so the UI can display them immediately
            run_context.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    tab_index=tab_index,
                    obj=SearchToolQueriesDelta(
                        queries=[query],
                    ),
                )
            )

            # If needed, hybrid alpha, recency bias, etc. can be added here.
            top_chunks = search_pipeline(
                db_session=db_session,
                # TODO optimize this with different set of keywords potentially
                chunk_search_request=ChunkSearchRequest(
                    query=query,
                    user_selected_filters=self.user_selected_filters,
                    bypass_acl=self.bypass_acl,
                    limit=override_kwargs.num_hits,
                ),
                project_id=self.project_id,
                document_index=self.document_index,
                user=self.user,
                persona=self.persona,
            )

            top_sections = merge_individual_chunks(top_chunks)

            # Convert InferenceSections to SavedSearchDocs for emission
            saved_search_docs = convert_inference_sections_to_search_docs(
                top_sections, is_internet=False
            )

            # Emit the documents
            run_context.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    tab_index=tab_index,
                    obj=SearchToolDocumentsDelta(
                        documents=saved_search_docs,
                    ),
                )
            )

            # Convert InferenceSections to SearchDoc objects for the return value
            search_docs = SearchDoc.from_chunks_or_sections(top_sections)

            docs_str = _convert_search_docs_to_llm_string(
                top_sections=top_sections,
                citation_start=override_kwargs.starting_citation_num,
                limit=override_kwargs.max_llm_chunks,
            )

            return ToolResponse(
                # Typically the rich response will give more docs in case it needs to be displayed in the UI
                rich_response=SearchDocsResponse(search_docs=search_docs),
                # The LLM facing response typically includes less docs to cut down on noise and token usage
                llm_facing_response=docs_str,
            )

        finally:
            # Always close the session to release database connections
            db_session.close()
