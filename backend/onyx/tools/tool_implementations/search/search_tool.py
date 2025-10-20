import copy
import json
from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from typing import cast
from typing import TypeVar

from sqlalchemy.orm import Session

from onyx.chat.chat_utils import llm_doc_from_inference_section
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import ContextualPruningConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.chat.models import SectionRelevancePiece
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.citations_prompt import compute_max_llm_input_tokens
from onyx.chat.prune_and_merge import prune_and_merge_sections
from onyx.chat.prune_and_merge import prune_sections
from onyx.configs.chat_configs import CONTEXT_CHUNKS_ABOVE
from onyx.configs.chat_configs import CONTEXT_CHUNKS_BELOW
from onyx.configs.model_configs import GEN_AI_MODEL_FALLBACK_MAX_TOKENS
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import QueryFlow
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import SearchRequest
from onyx.context.search.models import UserFileFilters
from onyx.context.search.pipeline import SearchPipeline
from onyx.context.search.pipeline import section_relevance_list_impl
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.onyxbot.slack.models import SlackContext
from onyx.secondary_llm_flows.choose_search import check_if_need_search
from onyx.secondary_llm_flows.query_expansion import history_based_query_rephrase
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import SearchQueryInfo
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_utils import llm_doc_to_dict
from onyx.tools.tool_implementations.search_like_tool_utils import (
    build_next_prompt_for_search_like_tool,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

SEARCH_RESPONSE_SUMMARY_ID = "search_response_summary"
SECTION_RELEVANCE_LIST_ID = "section_relevance_list"
SEARCH_EVALUATION_ID = "llm_doc_eval"
QUERY_FIELD = "query"


class SearchResponseSummary(SearchQueryInfo):
    top_sections: list[InferenceSection]
    rephrased_query: str | None = None
    predicted_flow: QueryFlow | None


SEARCH_TOOL_DESCRIPTION = """
Runs a semantic search over the user's knowledge base. The default behavior is to use this tool. \
The only scenario where you should not use this tool is if:

- There is sufficient information in chat history to FULLY and ACCURATELY answer the query AND \
additional information or details would provide little or no value.
- The query is some form of request that does not require additional information to handle.

HINT: if you are unfamiliar with the user input OR think the user input is a typo, use this tool.
"""


class SearchTool(Tool[SearchToolOverrideKwargs]):
    _NAME = "run_search"
    _DISPLAY_NAME = "Internal Search"
    _DESCRIPTION = SEARCH_TOOL_DESCRIPTION

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        user: User | None,
        persona: Persona,
        retrieval_options: RetrievalDetails | None,
        prompt_config: PromptConfig,
        llm: LLM,
        fast_llm: LLM,
        document_pruning_config: DocumentPruningConfig,
        answer_style_config: AnswerStyleConfig,
        evaluation_type: LLMEvaluationType,
        # if specified, will not actually run a search and will instead return these
        # sections. Used when the user selects specific docs to talk to
        selected_sections: list[InferenceSection] | None = None,
        chunks_above: int | None = None,
        chunks_below: int | None = None,
        full_doc: bool = False,
        bypass_acl: bool = False,
        rerank_settings: RerankingDetails | None = None,
        slack_context: SlackContext | None = None,
    ) -> None:
        self.user = user
        self.persona = persona
        self.retrieval_options = retrieval_options
        self.prompt_config = prompt_config
        self.llm = llm
        self.fast_llm = fast_llm
        self.evaluation_type = evaluation_type

        self.selected_sections = selected_sections

        self.full_doc = full_doc
        self.bypass_acl = bypass_acl
        self.db_session = db_session
        self.slack_context = slack_context

        # Log Slack context in SearchTool constructor
        if slack_context:
            logger.info(f"SearchTool: Slack context captured: {slack_context}")
        else:
            logger.info("SearchTool: No Slack context provided")

        # Only used via API
        self.rerank_settings = rerank_settings

        self.chunks_above = (
            chunks_above
            if chunks_above is not None
            else (
                persona.chunks_above
                if persona.chunks_above is not None
                else CONTEXT_CHUNKS_ABOVE
            )
        )
        self.chunks_below = (
            chunks_below
            if chunks_below is not None
            else (
                persona.chunks_below
                if persona.chunks_below is not None
                else CONTEXT_CHUNKS_BELOW
            )
        )

        # For small context models, don't include additional surrounding context
        # The 3 here for at least minimum 1 above, 1 below and 1 for the middle chunk

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

        self._id = tool_id

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

    """For LLMs that don't support tool calling"""

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        if not force_run and not check_if_need_search(
            query=query, history=history, llm=llm
        ):
            return None

        rephrased_query = history_based_query_rephrase(
            query=query, history=history, llm=llm
        )
        return {QUERY_FIELD: rephrased_query}

    """Actual tool execution"""

    def _build_response_for_specified_sections(
        self, query: str
    ) -> Generator[ToolResponse, None, None]:
        if self.selected_sections is None:
            raise ValueError("Sections must be specified")

        yield ToolResponse(
            id=SEARCH_RESPONSE_SUMMARY_ID,
            response=SearchResponseSummary(
                rephrased_query=None,
                top_sections=[],
                predicted_flow=None,
                predicted_search=None,
                final_filters=IndexFilters(access_control_list=None),  # dummy filters
                recency_bias_multiplier=1.0,
            ),
        )

        # Build selected sections for specified documents
        selected_sections = [
            SectionRelevancePiece(
                relevant=True,
                document_id=section.center_chunk.document_id,
                chunk_id=section.center_chunk.chunk_id,
            )
            for section in self.selected_sections
        ]

        yield ToolResponse(
            id=SECTION_RELEVANCE_LIST_ID,
            response=selected_sections,
        )

        final_context_sections = prune_and_merge_sections(
            sections=self.selected_sections,
            section_relevance_list=None,
            prompt_config=self.prompt_config,
            llm_config=self.llm.config,
            question=query,
            contextual_pruning_config=self.contextual_pruning_config,
        )

        llm_docs = [
            llm_doc_from_inference_section(section)
            for section in final_context_sections
        ]

        yield ToolResponse(id=FINAL_CONTEXT_DOCUMENTS_ID, response=llm_docs)

    def run(
        self, override_kwargs: SearchToolOverrideKwargs | None = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        query = cast(str, llm_kwargs[QUERY_FIELD])
        original_query = query
        precomputed_query_embedding = None
        precomputed_is_keyword = None
        precomputed_keywords = None
        force_no_rerank = False
        alternate_db_session = None
        retrieved_sections_callback = None
        skip_query_analysis = False
        user_file_ids = None
        project_id = None
        document_sources = None
        time_cutoff = None
        expanded_queries = None
        kg_entities = None
        kg_relationships = None
        kg_terms = None
        kg_sources = None
        kg_chunk_id_zero_only = False
        if override_kwargs:
            original_query = override_kwargs.original_query or query
            precomputed_is_keyword = override_kwargs.precomputed_is_keyword
            precomputed_keywords = override_kwargs.precomputed_keywords
            precomputed_query_embedding = override_kwargs.precomputed_query_embedding
            force_no_rerank = use_alt_not_None(override_kwargs.force_no_rerank, False)
            alternate_db_session = override_kwargs.alternate_db_session
            retrieved_sections_callback = override_kwargs.retrieved_sections_callback
            skip_query_analysis = use_alt_not_None(
                override_kwargs.skip_query_analysis, False
            )
            user_file_ids = override_kwargs.user_file_ids
            project_id = override_kwargs.project_id
            document_sources = override_kwargs.document_sources
            time_cutoff = override_kwargs.time_cutoff
            expanded_queries = override_kwargs.expanded_queries
            kg_entities = override_kwargs.kg_entities
            kg_relationships = override_kwargs.kg_relationships
            kg_terms = override_kwargs.kg_terms
            kg_sources = override_kwargs.kg_sources
            kg_chunk_id_zero_only = override_kwargs.kg_chunk_id_zero_only or False

        if self.selected_sections:
            yield from self._build_response_for_specified_sections(query)
            return

        retrieval_options = copy.deepcopy(self.retrieval_options) or RetrievalDetails()
        if document_sources or time_cutoff:
            # if empty, just start with an empty filters object
            if not retrieval_options.filters:
                retrieval_options.filters = BaseFilters()

            # Handle document sources
            if document_sources:
                source_types = retrieval_options.filters.source_type or []
                retrieval_options.filters.source_type = list(
                    set(source_types + document_sources)
                )

            # Handle time cutoff
            if time_cutoff:
                # Overwrite time-cutoff should supercede existing time-cutoff, even if defined
                retrieval_options.filters.time_cutoff = time_cutoff

        retrieval_options = copy.deepcopy(retrieval_options) or RetrievalDetails()
        retrieval_options.filters = retrieval_options.filters or BaseFilters()
        if kg_entities:
            retrieval_options.filters.kg_entities = kg_entities
        if kg_relationships:
            retrieval_options.filters.kg_relationships = kg_relationships
        if kg_terms:
            retrieval_options.filters.kg_terms = kg_terms
        if kg_sources:
            retrieval_options.filters.kg_sources = kg_sources
        if kg_chunk_id_zero_only:
            retrieval_options.filters.kg_chunk_id_zero_only = kg_chunk_id_zero_only

        search_pipeline = SearchPipeline(
            search_request=SearchRequest(
                query=query,
                evaluation_type=(
                    LLMEvaluationType.SKIP if force_no_rerank else self.evaluation_type
                ),
                human_selected_filters=(
                    retrieval_options.filters if retrieval_options else None
                ),
                user_file_filters=UserFileFilters(
                    user_file_ids=user_file_ids,
                    project_id=project_id,
                ),
                persona=self.persona,
                offset=(retrieval_options.offset if retrieval_options else None),
                limit=retrieval_options.limit if retrieval_options else None,
                rerank_settings=(
                    RerankingDetails(
                        rerank_model_name=None,
                        rerank_api_url=None,
                        rerank_provider_type=None,
                        rerank_api_key=None,
                        num_rerank=0,
                        disable_rerank_for_streaming=True,
                    )
                    if force_no_rerank
                    else self.rerank_settings
                ),
                chunks_above=self.chunks_above,
                chunks_below=self.chunks_below,
                full_doc=self.full_doc,
                enable_auto_detect_filters=(
                    retrieval_options.enable_auto_detect_filters
                    if retrieval_options
                    else None
                ),
                precomputed_query_embedding=precomputed_query_embedding,
                precomputed_is_keyword=precomputed_is_keyword,
                precomputed_keywords=precomputed_keywords,
                # add expanded queries
                expanded_queries=expanded_queries,
                original_query=original_query,
            ),
            user=self.user,
            llm=self.llm,
            fast_llm=self.fast_llm,
            skip_query_analysis=skip_query_analysis,
            bypass_acl=self.bypass_acl,
            db_session=alternate_db_session or self.db_session,
            prompt_config=self.prompt_config,
            retrieved_sections_callback=retrieved_sections_callback,
            contextual_pruning_config=self.contextual_pruning_config,
            slack_context=self.slack_context,  # Pass Slack context
        )

        search_query_info = SearchQueryInfo(
            predicted_search=search_pipeline.search_query.search_type,
            final_filters=search_pipeline.search_query.filters,
            recency_bias_multiplier=search_pipeline.search_query.recency_bias_multiplier,
        )
        yield from yield_search_responses(
            query=query,
            # give back the merged sections to prevent duplicate docs from appearing in the UI
            get_retrieved_sections=lambda: search_pipeline.merged_retrieved_sections,
            get_final_context_sections=lambda: search_pipeline.final_context_sections,
            search_query_info=search_query_info,
            get_section_relevance=lambda: search_pipeline.section_relevance,
            search_tool=self,
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        final_docs = cast(
            list[LlmDoc],
            next(arg.response for arg in args if arg.id == FINAL_CONTEXT_DOCUMENTS_ID),
        )
        # NOTE: need to do this json.loads(doc.json()) stuff because there are some
        # subfields that are not serializable by default (datetime)
        # this forces pydantic to make them JSON serializable for us
        return [json.loads(doc.model_dump_json()) for doc in final_docs]

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
        )


# Allows yielding the same responses as a SearchTool without being a SearchTool.
# SearchTool passed in to allow for access to SearchTool properties.
# We can't just call SearchTool methods in the graph because we're operating on
# the retrieved docs (reranking, deduping, etc.) after the SearchTool has run.
#
# The various inference sections are passed in as functions to allow for lazy
# evaluation. The SearchPipeline object properties that they correspond to are
# actually functions defined with @property decorators, and passing them into
# this function causes them to get evaluated immediately which is undesirable.
def yield_search_responses(
    query: str,
    get_retrieved_sections: Callable[[], list[InferenceSection]],
    get_final_context_sections: Callable[[], list[InferenceSection]],
    search_query_info: SearchQueryInfo,
    get_section_relevance: Callable[[], list[SectionRelevancePiece] | None],
    search_tool: SearchTool,
) -> Generator[ToolResponse, None, None]:
    yield ToolResponse(
        id=SEARCH_RESPONSE_SUMMARY_ID,
        response=SearchResponseSummary(
            rephrased_query=query,
            top_sections=get_retrieved_sections(),
            predicted_flow=QueryFlow.QUESTION_ANSWER,
            predicted_search=search_query_info.predicted_search,
            final_filters=search_query_info.final_filters,
            recency_bias_multiplier=search_query_info.recency_bias_multiplier,
        ),
    )

    section_relevance = get_section_relevance()
    yield ToolResponse(
        id=SECTION_RELEVANCE_LIST_ID,
        response=section_relevance,
    )

    final_context_sections = get_final_context_sections()

    # Use the section_relevance we already computed above
    pruned_sections = prune_sections(
        sections=final_context_sections,
        section_relevance_list=section_relevance_list_impl(
            section_relevance, final_context_sections
        ),
        prompt_config=search_tool.prompt_config,
        llm_config=search_tool.llm.config,
        question=query,
        contextual_pruning_config=search_tool.contextual_pruning_config,
    )
    llm_docs = [llm_doc_from_inference_section(section) for section in pruned_sections]

    yield ToolResponse(id=FINAL_CONTEXT_DOCUMENTS_ID, response=llm_docs)


T = TypeVar("T")


def use_alt_not_None(value: T | None, alt: T) -> T:
    return value if value is not None else alt
