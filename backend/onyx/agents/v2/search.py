from __future__ import annotations

import json
from time import monotonic
from typing import Any, Callable, cast

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.v2.models import (
    ExecutionContext,
    RegisteredTool,
    SearchFeedback,
    ToolOutput,
)
from onyx.agents.v2.search_expansion_context import ExpansionStrategy
from onyx.agents.v2.search_feedback import (
    EvidenceHistory,
    retrieval_outcome,
    source_scope,
)
from onyx.chat.emitter import NullEmitter
from onyx.configs.constants import MessageType
from onyx.context.search.models import (
    BaseFilters,
    PersonaSearchInfo,
    SearchDocsResponse,
)
from onyx.db.models import User
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import (
    LanguageModelInput,
    ReasoningEffort,
    SystemMessage,
    ToolChoiceOptions,
    UserMessage,
)
from onyx.prompts.harness_v2 import CONCISE_SEARCH_ANSWER_PROMPT, SEARCH_ANSWER_PROMPT
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    SearchToolFilterDelta,
    SearchToolQueriesDelta,
)
from onyx.tools.models import ChatMinimalTextMessage, SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span, record_llm_response


class SearchObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1, max_length=4096)


class NavigationObjective(SearchObjective):
    candidate_handle: str | None = Field(default=None, max_length=80)
    offset: int = Field(default=0, ge=0)


class DocumentObjective(NavigationObjective):
    read_citation: int | None = Field(default=None, ge=1)
    start_chunk: int = Field(default=0, ge=0)


class RecordObjective(NavigationObjective):
    record_query: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional short keyword query for finding primary records. Include the record "
        "type and discriminating subject terms from the question or observed evidence. "
        "Executed verbatim without query expansion using keyword-weighted hybrid retrieval.",
    )


class ReceiptEmitter(NullEmitter):
    def __init__(self, observer: Callable[[Packet], None] | None = None) -> None:
        super().__init__()
        self.observer = observer
        self.queries: list[str] = []
        self.filters: dict[str, Any] = {}

    def emit(self, packet: Packet) -> None:
        if self.observer is not None:
            self.observer(packet)
        if isinstance(packet.obj, SearchToolQueriesDelta):
            self.queries = list(packet.obj.queries)
        elif isinstance(packet.obj, SearchToolFilterDelta):
            self.filters = packet.obj.model_dump(mode="json")


class InternalSearchAnswer:
    def __init__(
        self,
        *,
        tool_id: int,
        user: User,
        persona: PersonaSearchInfo,
        filters: BaseFilters | None,
        index: DocumentIndex,
        llm: LLM,
        max_answer_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
        auto_detect_filters: bool = True,
        concise_answers: bool = False,
        synthesize_answer: bool = False,
        feedback: SearchFeedback = "off",
        candidate_preparation: bool = False,
        hierarchical_selection: bool = False,
        final_selection_limit: int = 10,
        document_read: bool = False,
        task_anchor: bool = False,
        record_queries: bool = False,
        expansion_strategy: ExpansionStrategy = "objective",
        packet_observer: Callable[[Packet], None] | None = None,
        response_observer: Callable[[SearchDocsResponse], None] | None = None,
    ) -> None:
        self.packet_observer = packet_observer
        self.response_observer = response_observer
        self.tool_id = tool_id
        self.user = user
        self.persona = persona
        self.filters = filters
        self.index = index
        self.llm = llm
        self.max_answer_tokens = max_answer_tokens
        self.reasoning_effort = reasoning_effort
        self.auto_detect_filters = auto_detect_filters
        self.synthesize_answer = synthesize_answer
        self.answer_prompt = (
            CONCISE_SEARCH_ANSWER_PROMPT if concise_answers else SEARCH_ANSWER_PROMPT
        )
        self.next_citation = 1
        self.feedback = feedback
        self.candidate_preparation = candidate_preparation
        self.hierarchical_selection = hierarchical_selection
        self.final_selection_limit = final_selection_limit
        self.document_read = document_read
        self.task_anchor = task_anchor
        self.record_queries = record_queries
        from onyx.agents.v2.search_expansion_context import SearchExpansionContext

        self.expansion_context = SearchExpansionContext(expansion_strategy)
        self.known_citations: dict[int, str] = {}
        self.evidence_history = EvidenceHistory()
        from onyx.agents.v2.search_navigation import SearchNavigation

        self.navigation = SearchNavigation()
        self.last_diagnostics: dict[str, Any] = {}

    def registered(self) -> RegisteredTool:
        return RegisteredTool(
            name="internal_search",
            description=(
                "Search authorized company documents for a precise objective. Returns "
                "evidence, citations, executed queries, and scope. "
                "The caller writes the final answer unless synthesis is enabled. "
                "For follow-ups, state the new missing fact or dependency explicitly."
                + (
                    " Navigation receipts include alternative candidate handles. Supply candidate_handle "
                    "and optional character offset with the objective to inspect cached text without a new search."
                    if self.feedback == "navigation"
                    else ""
                )
                + (
                    " To read more of an already-found document, supply read_citation with its numeric "
                    "citation and optional start_chunk. This fetches six authorized chunks without query expansion."
                    if self.document_read
                    else ""
                )
                + (
                    " For counts or inventories, retrieve underlying records rather than policies or "
                    "account summaries. If results miss the requested record type, use record_query "
                    "with short record-type and topic terms. For later calls, vary the missing "
                    "record type or subject instead of repeating a broad objective. This does not "
                    "guarantee exhaustive coverage or exclude previously seen records."
                    if self.record_queries
                    else ""
                )
            ),
            parameters=(
                RecordObjective
                if self.record_queries
                else DocumentObjective
                if self.document_read
                else NavigationObjective
                if self.feedback == "navigation"
                else SearchObjective
            ).model_json_schema(),
            execute=self.run,
            pinned=True,
            requires_approval=False,
        )

    def run(  # noqa: C901
        self, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolOutput:
        self.last_diagnostics = {}
        schema = (
            RecordObjective
            if self.record_queries
            else DocumentObjective
            if self.document_read
            else NavigationObjective
            if self.feedback == "navigation"
            else SearchObjective
        )
        parsed = schema.model_validate(arguments)
        if isinstance(parsed, DocumentObjective) and parsed.read_citation is not None:
            if parsed.candidate_handle:
                return ToolOutput(
                    status="error",
                    content="Choose either read_citation or candidate_handle, not both.",
                )
            from onyx.agents.v2.document_read import read_cited_document

            result = read_cited_document(
                index=self.index,
                user=self.user,
                filters=self.filters,
                known_citations=self.known_citations,
                read_citation=parsed.read_citation,
                start_chunk=parsed.start_chunk,
                citation=self.next_citation,
            )
            if result.citation_mapping:
                self.known_citations.update(result.citation_mapping)
                self.next_citation = max(result.citation_mapping) + 1
            return result
        if isinstance(parsed, NavigationObjective):
            if parsed.candidate_handle:
                result = self.navigation.inspect(
                    parsed.candidate_handle, parsed.offset, self.next_citation
                )
                if result.citation_mapping:
                    self.next_citation = max(result.citation_mapping) + 1
                    self.known_citations.update(result.citation_mapping)
                return result
        objective = parsed.objective.strip()
        if not objective:
            raise ValueError("Search objective cannot be blank")
        emitter = ReceiptEmitter(self.packet_observer)
        record_query = (
            parsed.record_query.strip()
            if isinstance(parsed, RecordObjective) and parsed.record_query
            else None
        )
        if (
            isinstance(parsed, RecordObjective)
            and parsed.record_query is not None
            and not record_query
        ):
            raise ValueError("Record query cannot be blank")
        search = SearchTool(
            tool_id=self.tool_id,
            emitter=emitter,
            user=self.user,
            persona_search_info=self.persona,
            llm=self.llm,
            document_index=self.index,
            user_selected_filters=self.filters,
            project_id_filter=None,
            bypass_acl=False,
            enable_slack_search=False,
            auto_detect_filters=self.auto_detect_filters,
            candidate_preparation=self.candidate_preparation,
            hierarchical_selection=self.hierarchical_selection,
            final_selection_limit=self.final_selection_limit,
            record_query=record_query,
        )
        retrieval_started = monotonic()
        override = SearchToolOverrideKwargs(
            original_query=context.task if self.task_anchor else objective,
            message_history=[
                ChatMinimalTextMessage(
                    message=text,
                    message_type=MessageType.USER
                    if role == "user"
                    else MessageType.ASSISTANT,
                )
                for role, text in self.expansion_context.messages(
                    context.task, objective, self.task_anchor
                )
            ],
            skip_query_expansion=bool(record_query),
            starting_citation_num=self.next_citation,
            include_link=True,
            include_retrieval_candidates=self.feedback == "navigation",
        )
        if self.hierarchical_selection:
            override.num_hits = 100
        response = search.run(
            placement=Placement(turn_index=0),
            override_kwargs=override,
            queries=[objective],
        )
        retrieval_ms = (monotonic() - retrieval_started) * 1000
        if not isinstance(response.rich_response, SearchDocsResponse):
            raise ValueError("Internal search returned an unexpected result type")
        rich = response.rich_response
        if self.response_observer is not None:
            self.response_observer(rich)
        if self.feedback == "navigation":
            self.last_diagnostics = (
                rich.model_dump(mode="json").get("search_tool_diagnostics") or {}
            )
        citations = dict(rich.citation_mapping)
        self.known_citations.update(citations)
        if citations:
            self.next_citation = max(citations) + 1
        receipt = {
            "objective": objective,
            "selection_question": context.task if self.task_anchor else objective,
            "executed_queries": emitter.queries,
            "query_capture_available": bool(emitter.queries),
            "expansion_requested": not bool(record_query),
            "record_query": record_query,
            "scope": emitter.filters,
            "requested_filters": self.filters.model_dump(mode="json")
            if self.filters
            else None,
            "persona_document_sets": self.persona.document_set_names,
            "retrieved_document_count": len({d.document_id for d in rich.search_docs}),
            "evidence_document_count": len(set(citations.values())),
            "coverage": "Returned evidence is not an exhaustive corpus search",
            "retrieval_ms": retrieval_ms,
            "answer_synthesis_ms": None,
            "answer_synthesis_enabled": self.synthesize_answer,
        }
        if self.document_read:
            receipt["document_read"] = (
                "For a missing table or later section, use internal_search with read_citation and start_chunk=0. Follow next_chunk to read another page. read_result only reads already-stored text."
            )
        self.expansion_context.observe(
            objective,
            emitter.queries,
            [
                cast(Any, document).model_dump(mode="json")
                for document in rich.search_docs
            ],
        )
        receipt["expansion_strategy"] = self.expansion_context.strategy
        content = response.llm_facing_response
        selection_degraded = bool(
            self.last_diagnostics.get("retrieval", {})
            .get("hierarchical_selection", {})
            .get("selection_degraded")
        )
        if selection_degraded:
            receipt["selection_degraded"] = True
            receipt["selection_warning"] = (
                "Some document selection used a budget/error fallback. Returned order is not a complete relevance judgment. Preserve earlier evidence; absence here does not mean the answer is absent from retrieved candidates."
            )
        if self.feedback == "navigation":
            receipt["navigation"] = self.navigation.observe(
                self.last_diagnostics, citations
            )
            receipt["evidence_novelty"] = self.evidence_history.observe(
                content, citations
            )
        elif self.feedback == "novelty":
            receipt["evidence_novelty"] = self.evidence_history.observe(
                content, citations
            )
        elif self.feedback == "source_scope":
            content = source_scope(content, rich)
        elif self.feedback == "outcomes":
            receipt["retrieval_outcome"] = retrieval_outcome(rich)
        if context.cancelled():
            return ToolOutput(
                status="partial",
                content=content,
                receipt=receipt,
                document_ids=list(dict.fromkeys(citations.values())),
                citation_mapping=citations,
            )
        if not self.synthesize_answer:
            receipt["answer_synthesis_ms"] = 0.0
            return ToolOutput(
                status="partial" if selection_degraded else "success",
                content=content,
                receipt=receipt,
                document_ids=list(dict.fromkeys(citations.values())),
                citation_mapping=citations,
            )
        prompt: LanguageModelInput = [
            SystemMessage(content=self.answer_prompt),
            UserMessage(
                content=json.dumps(
                    {
                        "overall_task": context.task,
                        "retrieval_objective": objective,
                        "evidence": response.llm_facing_response,
                    }
                )
            ),
        ]
        synthesis_started = monotonic()
        with llm_generation_span(
            self.llm,
            flow=LLMFlow.AGENT_HARNESS_V2_SEARCH_ANSWER,
            input_messages=prompt,
            tools=[],
        ) as span:
            answer = self.llm.invoke(
                prompt=prompt,
                tools=[],
                tool_choice=ToolChoiceOptions.NONE,
                max_tokens=self.max_answer_tokens,
                reasoning_effort=self.reasoning_effort,
                user_identity=LLMUserIdentity(user_id=str(self.user.id)),
                total_timeout_override=context.remaining_seconds,
            )
            record_llm_response(span, answer)
        receipt["answer_synthesis_ms"] = (monotonic() - synthesis_started) * 1000
        text = (answer.choice.message.content or "").strip()
        status = (
            "success" if text and answer.choice.finish_reason == "stop" else "partial"
        )
        receipt["answer_finish_reason"] = answer.choice.finish_reason
        return ToolOutput(
            status=status,
            answer=text or None,
            content=json.dumps(
                {"answer": text, "evidence": response.llm_facing_response}
            ),
            receipt=receipt,
            document_ids=list(dict.fromkeys(citations.values())),
            citation_mapping=citations,
        )
