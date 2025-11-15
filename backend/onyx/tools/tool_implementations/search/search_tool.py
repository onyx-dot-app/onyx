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
from onyx.tools.tool import RunContextWrapper
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

    def get_llm_tool_response(
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

    def run_v2(
        self,
        run_context: RunContextWrapper[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError("SearchTool.run_v2 is not implemented.")

    # def _build_response_for_specified_sections(
    #     self, query: str
    # ) -> Generator[ToolResponse, None, None]:
    #     if self.selected_sections is None:
    #         raise ValueError("Sections must be specified")

    #     yield ToolResponse(
    #         id=SEARCH_RESPONSE_SUMMARY_ID,
    #         response=SearchResponseSummary(
    #             rephrased_query=None,
    #             top_sections=[],
    #             predicted_flow=None,
    #             predicted_search=None,
    #             final_filters=IndexFilters(access_control_list=None),  # dummy filters
    #             recency_bias_multiplier=1.0,
    #         ),
    #     )

    #     # Build selected sections for specified documents
    #     selected_sections = [
    #         SectionRelevancePiece(
    #             relevant=True,
    #             document_id=section.center_chunk.document_id,
    #             chunk_id=section.center_chunk.chunk_id,
    #         )
    #         for section in self.selected_sections
    #     ]

    #     yield ToolResponse(
    #         id=SECTION_RELEVANCE_LIST_ID,
    #         response=selected_sections,
    #     )

    #     final_context_sections = prune_and_merge_sections(
    #         sections=self.selected_sections,
    #         section_relevance_list=None,
    #         prompt_config=self.prompt_config,
    #         llm_config=self.llm.config,
    #         question=query,
    #         contextual_pruning_config=self.contextual_pruning_config,
    #     )

    #     llm_docs = [
    #         llm_doc_from_inference_section(section)
    #         for section in final_context_sections
    #     ]

    #     yield ToolResponse(id=FINAL_CONTEXT_DOCUMENTS_ID, response=llm_docs)

    # def run(
    #     self, override_kwargs: SearchToolOverrideKwargs | None = None, **llm_kwargs: Any
    # ) -> Generator[ToolResponse, None, None]:
    #     query = cast(str, llm_kwargs[QUERY_FIELD])
    #     original_query = query
    #     precomputed_query_embedding = None
    #     precomputed_is_keyword = None
    #     precomputed_keywords = None
    #     force_no_rerank = False
    #     alternate_db_session = None
    #     retrieved_sections_callback = None
    #     skip_query_analysis = False
    #     user_file_ids = None
    #     project_id = None
    #     document_sources = None
    #     time_cutoff = None
    #     expanded_queries = None
    #     kg_entities = None
    #     kg_relationships = None
    #     kg_terms = None
    #     kg_sources = None
    #     kg_chunk_id_zero_only = False
    #     if override_kwargs:
    #         original_query = override_kwargs.original_query or query
    #         precomputed_is_keyword = override_kwargs.precomputed_is_keyword
    #         precomputed_keywords = override_kwargs.precomputed_keywords
    #         precomputed_query_embedding = override_kwargs.precomputed_query_embedding
    #         force_no_rerank = use_alt_not_None(override_kwargs.force_no_rerank, False)
    #         alternate_db_session = override_kwargs.alternate_db_session
    #         retrieved_sections_callback = override_kwargs.retrieved_sections_callback
    #         skip_query_analysis = use_alt_not_None(
    #             override_kwargs.skip_query_analysis, False
    #         )
    #         user_file_ids = override_kwargs.user_file_ids
    #         project_id = override_kwargs.project_id
    #         document_sources = override_kwargs.document_sources
    #         time_cutoff = override_kwargs.time_cutoff
    #         expanded_queries = override_kwargs.expanded_queries
    #         kg_entities = override_kwargs.kg_entities
    #         kg_relationships = override_kwargs.kg_relationships
    #         kg_terms = override_kwargs.kg_terms
    #         kg_sources = override_kwargs.kg_sources
    #         kg_chunk_id_zero_only = override_kwargs.kg_chunk_id_zero_only or False

    #     if self.selected_sections:
    #         yield from self._build_response_for_specified_sections(query)
    #         return

    #     retrieval_options = copy.deepcopy(self.retrieval_options) or RetrievalDetails()
    #     if document_sources or time_cutoff:
    #         # if empty, just start with an empty filters object
    #         if not retrieval_options.filters:
    #             retrieval_options.filters = BaseFilters()

    #         # Handle document sources
    #         if document_sources:
    #             source_types = retrieval_options.filters.source_type or []
    #             retrieval_options.filters.source_type = list(
    #                 set(source_types + document_sources)
    #             )

    #         # Handle time cutoff
    #         if time_cutoff:
    #             # Overwrite time-cutoff should supercede existing time-cutoff, even if defined
    #             retrieval_options.filters.time_cutoff = time_cutoff

    #     retrieval_options = copy.deepcopy(retrieval_options) or RetrievalDetails()
    #     retrieval_options.filters = retrieval_options.filters or BaseFilters()
    #     if kg_entities:
    #         retrieval_options.filters.kg_entities = kg_entities
    #     if kg_relationships:
    #         retrieval_options.filters.kg_relationships = kg_relationships
    #     if kg_terms:
    #         retrieval_options.filters.kg_terms = kg_terms
    #     if kg_sources:
    #         retrieval_options.filters.kg_sources = kg_sources
    #     if kg_chunk_id_zero_only:
    #         retrieval_options.filters.kg_chunk_id_zero_only = kg_chunk_id_zero_only

    #     search_pipeline = SearchPipeline(
    #         search_request=SearchRequest(
    #             query=query,
    #             evaluation_type=(
    #                 LLMEvaluationType.SKIP if force_no_rerank else self.evaluation_type
    #             ),
    #             human_selected_filters=(
    #                 retrieval_options.filters if retrieval_options else None
    #             ),
    #             user_file_filters=UserFileFilters(
    #                 user_file_ids=user_file_ids,
    #                 project_id=project_id,
    #             ),
    #             persona=self.persona,
    #             offset=(retrieval_options.offset if retrieval_options else None),
    #             limit=retrieval_options.limit if retrieval_options else None,
    #             rerank_settings=(
    #                 RerankingDetails(
    #                     rerank_model_name=None,
    #                     rerank_api_url=None,
    #                     rerank_provider_type=None,
    #                     rerank_api_key=None,
    #                     num_rerank=0,
    #                     disable_rerank_for_streaming=True,
    #                 )
    #                 if force_no_rerank
    #                 else self.rerank_settings
    #             ),
    #             chunks_above=self.chunks_above,
    #             chunks_below=self.chunks_below,
    #             full_doc=self.full_doc,
    #             enable_auto_detect_filters=(
    #                 retrieval_options.enable_auto_detect_filters
    #                 if retrieval_options
    #                 else None
    #             ),
    #             precomputed_query_embedding=precomputed_query_embedding,
    #             precomputed_is_keyword=precomputed_is_keyword,
    #             precomputed_keywords=precomputed_keywords,
    #             # add expanded queries
    #             expanded_queries=expanded_queries,
    #             original_query=original_query,
    #         ),
    #         user=self.user,
    #         llm=self.llm,
    #         fast_llm=self.fast_llm,
    #         skip_query_analysis=skip_query_analysis,
    #         bypass_acl=self.bypass_acl,
    #         db_session=alternate_db_session or self.db_session,
    #         prompt_config=self.prompt_config,
    #         retrieved_sections_callback=retrieved_sections_callback,
    #         contextual_pruning_config=self.contextual_pruning_config,
    #         slack_context=self.slack_context,  # Pass Slack context
    #     )

    #     search_query_info = SearchQueryInfo(
    #         predicted_search=search_pipeline.search_query.search_type,
    #         final_filters=search_pipeline.search_query.filters,
    #         recency_bias_multiplier=search_pipeline.search_query.recency_bias_multiplier,
    #     )
    #     yield from yield_search_responses(
    #         query=query,
    #         # give back the merged sections to prevent duplicate docs from appearing in the UI
    #         get_retrieved_sections=lambda: search_pipeline.merged_retrieved_sections,
    #         get_final_context_sections=lambda: search_pipeline.final_context_sections,
    #         search_query_info=search_query_info,
    #         get_section_relevance=lambda: search_pipeline.section_relevance,
    #         search_tool=self,
    #     )

    # def final_result(self, *args: ToolResponse) -> JSON_ro:
    #     final_docs = cast(
    #         list[LlmDoc],
    #         next(arg.response for arg in args if arg.id == FINAL_CONTEXT_DOCUMENTS_ID),
    #     )
    #     # NOTE: need to do this json.loads(doc.json()) stuff because there are some
    #     # subfields that are not serializable by default (datetime)
    #     # this forces pydantic to make them JSON serializable for us
    #     return [json.loads(doc.model_dump_json()) for doc in final_docs]

    # def build_next_prompt(
    #     self,
    #     prompt_builder: AnswerPromptBuilder,
    #     tool_call_summary: ToolCallSummary,
    #     tool_responses: list[ToolResponse],
    #     using_tool_calling_llm: bool,
    # ) -> AnswerPromptBuilder:
    #     return build_next_prompt_for_search_like_tool(
    #         prompt_builder=prompt_builder,
    #         tool_call_summary=tool_call_summary,
    #         tool_responses=tool_responses,
    #         using_tool_calling_llm=using_tool_calling_llm,
    #         answer_style_config=self.answer_style_config,
    #         prompt_config=self.prompt_config,
    #     )


T = TypeVar("T")


def use_alt_not_None(value: T | None, alt: T) -> T:
    return value if value is not None else alt
