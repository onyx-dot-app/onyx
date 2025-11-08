import json
from collections.abc import Generator
from typing import Any
from typing import cast
from typing import TypeVar

from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.chat.chat_utils import llm_doc_from_inference_section
from onyx.chat.models import LlmDoc
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.db.connector import check_connectors_exist
from onyx.db.connector import check_federated_connectors_exist
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.onyxbot.slack.models import SlackContext
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_utils import llm_doc_to_dict
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_SEARCH_QUERIES_ID,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    SEARCH_INFERENCE_SECTIONS_ID,
)
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

SEARCH_EVALUATION_ID = "llm_doc_eval"
QUERY_FIELD = "query"


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


class SearchTool(Tool[SearchToolOverrideKwargs]):
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

    """Actual tool execution"""

    def run(
        self, override_kwargs: SearchToolOverrideKwargs | None = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        # Create a new thread-safe session for this execution
        # This prevents transaction conflicts when multiple search tools run in parallel
        db_session = self._get_thread_safe_session()
        try:
            query = cast(str, llm_kwargs[QUERY_FIELD])
            if not override_kwargs:
                raise RuntimeError("No override kwargs provided for search tool")

            # TODO this should be also passed in the history up to this point.

            # TODO use the original query.
            override_kwargs.original_query

            # Yield the queries early so the UI can display them immediately
            yield ToolResponse(
                id=FINAL_SEARCH_QUERIES_ID,
                response=["query"],
            )

            # If needed, hybrid alpha, recency bias, etc. can be added here.
            top_chunks = search_pipeline(
                db_session=db_session,
                # TODO optimize this with different set of keywords potentially
                chunk_search_request=ChunkSearchRequest(
                    query=query,
                    user_selected_filters=self.user_selected_filters,
                    bypass_acl=self.bypass_acl,
                ),
                project_id=self.project_id,
                document_index=self.document_index,
                user=self.user,
                persona=self.persona,
            )

            top_sections = merge_individual_chunks(top_chunks)

            # Yield the inference sections for consumers that need them
            yield ToolResponse(
                id=SEARCH_INFERENCE_SECTIONS_ID,
                response=top_sections,
            )

            llm_docs = [
                llm_doc_from_inference_section(section) for section in top_sections
            ]

            yield ToolResponse(
                id=FINAL_CONTEXT_DOCUMENTS_ID,
                response=llm_docs,
            )
        finally:
            # Always close the session to release database connections
            db_session.close()

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        final_docs = cast(
            list[LlmDoc],
            next(arg.response for arg in args if arg.id == FINAL_CONTEXT_DOCUMENTS_ID),
        )
        # NOTE: need to do this json.loads(doc.json()) stuff because there are some
        # subfields that are not serializable by default (datetime)
        # this forces pydantic to make them JSON serializable for us
        return [json.loads(doc.model_dump_json()) for doc in final_docs]


T = TypeVar("T")


def use_alt_not_None(value: T | None, alt: T) -> T:
    return value if value is not None else alt
