"""Translate shared messages and tool results into chat browser packets."""

from collections.abc import Mapping

from pydantic import BaseModel, JsonValue, TypeAdapter

from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import MessageRendering, PresentationMode
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.tool_definitions import (
    BASH_TOOL_NAME,
    CODING_AGENT_TOOL_NAME,
    GENERATE_ANSWER_TOOL_NAME,
)
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationContentEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallStartEvent,
    ToolResult,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import REQUEST_BODY
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool

HIDDEN_TOOLS = frozenset(
    {
        GENERATE_PLAN_TOOL_NAME,
        GENERATE_REPORT_TOOL_NAME,
        GENERATE_ANSWER_TOOL_NAME,
        THINK_TOOL_NAME,
    }
)

_STRING = TypeAdapter(str)
_STRINGS = TypeAdapter(list[str])


class ResponseLayout:
    """Allocate browser sections; child sections stay inside their parent tool tab."""

    def __init__(self) -> None:
        self._next_turn = 0
        self._next_sub_turn: dict[tuple[int, int], int] = {}

    def next_section(self, parent: Placement | None = None) -> Placement:
        if parent is None:
            placement = Placement(turn_index=self._next_turn)
            self._next_turn += 1
            return placement
        key = (parent.turn_index, parent.tab_index)
        index = self._next_sub_turn.get(key, 0)
        self._next_sub_turn[key] = index + 1
        return parent.model_copy(update={"sub_turn_index": index})


class MessageRenderer:
    """Append formatted text once, then close its browser sections on completion."""

    def __init__(
        self,
        settings: MessageRendering,
        documents: Mapping[str, SearchDoc],
        layout: ResponseLayout,
        parent: Placement | None = None,
    ) -> None:
        self.settings = settings
        self.layout = layout
        self.parent = parent
        self.answer = ""
        self.reasoning = ""
        self.citations: list[packets.CitationInfo] = []
        self.documents = [
            documents[key] for key in settings.document_ids if key in documents
        ]
        self._answer_placement: Placement | None = None
        self._reasoning_placement: Placement | None = None
        self._raw_text = ""
        self._raw_thinking = ""
        self._finished = False
        self.tool_placements: dict[str, Placement] = {}
        self.citation_processor = (
            DynamicCitationProcessor(citation_mode=settings.citation_mode)
            if settings.citation_mode is not None
            else None
        )
        if self.citation_processor:
            self.citation_processor.update_citation_mapping(
                {
                    number: documents[key]
                    for number, key in settings.citation_documents.items()
                    if key in documents
                }
            )

    @property
    def answer_started(self) -> bool:
        return self._answer_placement is not None

    def _append(self, text: str, *, thinking: bool = False) -> list[packets.Packet]:
        if not text or self.settings.mode == PresentationMode.SILENT:
            return []
        if thinking:
            self.reasoning += text
            if self.settings.mode == PresentationMode.CODING_THINKING:
                if self.parent is None:
                    raise ValueError("Coding output requires a parent tool placement")
                return [
                    packets.Packet(
                        placement=self.parent,
                        obj=packets.CodingAgentThinkingDelta(content=text),
                    )
                ]
            result = []
            if self._reasoning_placement is None:
                self._reasoning_placement = self.layout.next_section(self.parent)
                result.append(
                    packets.Packet(
                        placement=self._reasoning_placement,
                        obj=packets.ReasoningStart(),
                    )
                )
            result.append(
                packets.Packet(
                    placement=self._reasoning_placement,
                    obj=packets.ReasoningDelta(reasoning=text),
                )
            )
            return result
        self.answer += text
        if self.settings.mode == PresentationMode.CODING_THINKING:
            if self.parent is None:
                raise ValueError("Coding output requires a parent tool placement")
            return [
                packets.Packet(
                    placement=self.parent,
                    obj=packets.CodingAgentThinkingDelta(content=text),
                )
            ]
        result = []
        if self._answer_placement is None:
            result.extend(self._close_reasoning())
            self._answer_placement = self.layout.next_section(self.parent)
            if self.settings.mode == PresentationMode.PLAN:
                start: packets.PacketObj = packets.DeepResearchPlanStart()
            elif self.settings.mode == PresentationMode.REPORT:
                start = packets.IntermediateReportStart()
            else:
                start = packets.AgentResponseStart(
                    final_documents=self.documents,
                    pre_answer_processing_seconds=self.settings.pre_answer_seconds,
                )
            result.append(packets.Packet(placement=self._answer_placement, obj=start))
        if self.settings.mode == PresentationMode.PLAN:
            delta: packets.PacketObj = packets.DeepResearchPlanDelta(content=text)
        elif self.settings.mode == PresentationMode.REPORT:
            delta = packets.IntermediateReportDelta(content=text)
        else:
            delta = packets.AgentResponseDelta(content=text)
        result.append(packets.Packet(placement=self._answer_placement, obj=delta))
        return result

    def _content(self, text: str | None) -> list[packets.Packet]:
        if self.settings.text_as_thinking:
            return self._append(text or "", thinking=True)
        if self.citation_processor is None:
            return self._append(text or "")
        result = []
        for value in self.citation_processor.process_token(text):
            if isinstance(value, str):
                result.extend(self._append(value))
            else:
                self.citations.append(value)
                if self._answer_placement is not None:
                    result.append(
                        packets.Packet(placement=self._answer_placement, obj=value)
                    )
        return result

    def tool_placement(self, call_id: str) -> Placement:
        if call_id not in self.tool_placements:
            first = next(iter(self.tool_placements.values()), None)
            self.tool_placements[call_id] = (
                first.model_copy(update={"tab_index": len(self.tool_placements)})
                if first is not None and self.parent is None
                else self.layout.next_section(self.parent)
            )
        return self.tool_placements[call_id]

    def consume(self, event: GenerationContentEvent) -> list[packets.Packet]:
        if isinstance(event, TextDeltaEvent):
            self._raw_text += event.text
            return self._content(event.text)
        if isinstance(event, ThinkingDeltaEvent):
            self._raw_thinking += event.text
            return self._append(event.text, thinking=True)
        if (
            isinstance(event, (ToolCallStartEvent, ToolCallDeltaEvent))
            and event.tool_call.name == self.settings.think_tool
        ):
            text = event.argument_deltas.get("reasoning", "")
            self._raw_thinking += text
            return self._append(text, thinking=True)
        if (
            isinstance(event, (ToolCallStartEvent, ToolCallDeltaEvent))
            and event.tool_call.name
            and event.tool_call.name not in HIDDEN_TOOLS
        ):
            result = self._close_reasoning()
            placement = self.tool_placement(event.tool_call.id)
            if event.tool_call.name == PythonTool.NAME:
                result.append(
                    packets.Packet(
                        placement=placement,
                        obj=packets.ToolCallArgumentDelta(
                            tool_type=PythonTool.NAME,
                            argument_deltas=event.argument_deltas,
                        ),
                    )
                )
            return result
        return []

    def complete(self, message: AssistantMessage) -> list[packets.Packet]:
        if self._finished:
            return []
        # Nonstreaming providers and interrupted streams can deliver a final suffix.
        text = "".join(
            block.text for block in message.content if isinstance(block, TextContent)
        )
        thinking = "".join(
            block.text
            for block in message.content
            if isinstance(block, ThinkingContent)
        )
        for call in message.tool_calls:
            if call.name == self.settings.think_tool:
                thinking += _STRING.validate_python(call.arguments.get("reasoning", ""))
        result = []
        if thinking.startswith(self._raw_thinking):
            result.extend(
                self._append(thinking[len(self._raw_thinking) :], thinking=True)
            )
        if text.startswith(self._raw_text):
            result.extend(self._content(text[len(self._raw_text) :]))
        result.extend(self.finish())
        if text and not self.answer and not self.reasoning:
            result.extend(self._append(text))
            if self._answer_placement is not None:
                result.append(
                    packets.Packet(
                        placement=self._answer_placement, obj=packets.SectionEnd()
                    )
                )
        return result

    def _close_reasoning(self) -> list[packets.Packet]:
        if self._reasoning_placement is None:
            return []
        placement = self._reasoning_placement
        self._reasoning_placement = None
        return [
            packets.Packet(placement=placement, obj=packets.ReasoningDone()),
            packets.Packet(placement=placement, obj=packets.SectionEnd()),
        ]

    def finish(self) -> list[packets.Packet]:
        if self._finished:
            return []
        self._finished = True
        result = self._content(None)
        result.extend(self._close_reasoning())
        if self._answer_placement is not None:
            if self.settings.mode == PresentationMode.REPORT:
                result.append(
                    packets.Packet(
                        placement=self._answer_placement,
                        obj=packets.IntermediateReportCitedDocs(
                            cited_docs=self.documents
                        ),
                    )
                )
            result.append(
                packets.Packet(
                    placement=self._answer_placement, obj=packets.SectionEnd()
                )
            )
        return result


class ToolRenderer:
    """Project tool progress and final results without sending private tool state."""

    def __init__(
        self, call: ToolCall, placement: Placement, tool_id: int | None = None
    ) -> None:
        self.call = call
        self.placement = placement
        self.tool_id = tool_id
        self._queries: set[str] = set()
        self._documents: set[str] = set()
        self._last_details: BaseModel | None = None
        self.has_child_output = False
        self._stdout = ""
        self._stderr = ""
        self._files: set[str] = set()

    def start(self) -> list[packets.Packet]:
        name = self.call.name
        args = self.call.arguments
        objects: list[packets.PacketObj]
        if name in {SearchTool.NAME, WebSearchTool.NAME}:
            objects = [
                packets.SearchToolStart(is_internet_search=name == WebSearchTool.NAME)
            ]
            queries = _STRINGS.validate_python(args.get("queries", []))
            self._queries.update(queries)
            objects.append(packets.SearchToolQueriesDelta(queries=queries))
        elif name == OpenURLTool.NAME:
            objects = [
                packets.OpenUrlStart(),
                packets.OpenUrlUrls(
                    urls=_STRINGS.validate_python(args.get("urls", []))
                ),
            ]
        elif name == PythonTool.NAME:
            objects = [
                packets.PythonToolStart(
                    code=_STRING.validate_python(args.get("code", ""))
                )
            ]
        elif name == BASH_TOOL_NAME:
            objects = [
                packets.BashToolStart(cmd=_STRING.validate_python(args.get("cmd", "")))
            ]
        elif name == FileReaderTool.NAME:
            objects = [packets.FileReaderStart()]
        elif name == MemoryTool.NAME:
            objects = [packets.MemoryToolStart()]
        elif name == ImageGenerationTool.NAME:
            objects = [packets.ImageGenerationToolStart()]
        elif name == RESEARCH_AGENT_TOOL_NAME:
            objects = [
                packets.ResearchAgentStart(
                    research_task=_STRING.validate_python(args.get("task", ""))
                )
            ]
        elif name == CODING_AGENT_TOOL_NAME:
            objects = [
                packets.CodingAgentStart(
                    query=_STRING.validate_python(args.get("query", "")),
                    repo=_STRING.validate_python(args.get("github_repo", "")),
                )
            ]
        else:
            objects = [
                packets.CustomToolStart(tool_name=name, tool_id=self.tool_id),
                packets.CustomToolArgs(
                    tool_name=name,
                    tool_args={
                        key: value for key, value in args.items() if key != REQUEST_BODY
                    },
                ),
            ]
        objects.append(
            packets.ToolCallDebug(
                tool_call_id=self.call.id,
                tool_name=name,
                tool_args={
                    key: value for key, value in args.items() if key != REQUEST_BODY
                },
            )
        )
        return [packets.Packet(placement=self.placement, obj=obj) for obj in objects]

    def update(
        self, details: BaseModel | None, content: str = ""
    ) -> list[packets.Packet]:
        objects: list[packets.PacketObj] = []
        if isinstance(details, SearchDocsResponse):
            docs = details.displayed_docs or details.search_docs
            new_docs = [doc for doc in docs if doc.document_id not in self._documents]
            self._documents.update(doc.document_id for doc in docs)
            if self.call.name == OpenURLTool.NAME:
                if new_docs:
                    objects.append(packets.OpenUrlDocuments(documents=new_docs))
            else:
                queries = [
                    query for query in details.queries if query not in self._queries
                ]
                self._queries.update(queries)
                if queries:
                    objects.append(packets.SearchToolQueriesDelta(queries=queries))
                objects.append(
                    packets.SearchToolFilterDelta(
                        sources=details.sources,
                        time_filter_start=details.time_filter_start,
                        time_filter_end=details.time_filter_end,
                    )
                )
                if new_docs:
                    objects.append(packets.SearchToolDocumentsDelta(documents=new_docs))
        elif details is not None and details == self._last_details:
            return []
        elif isinstance(details, FileReadResult):
            objects.append(
                packets.FileReaderResult(
                    file_name=details.file_name,
                    file_id=details.file_id,
                    start_char=details.start_char,
                    end_char=details.end_char,
                    total_chars=details.total_chars,
                    preview_start=details.preview_start,
                    preview_end=details.preview_end,
                )
            )
        elif isinstance(details, MemoryUpdated):
            objects.append(
                packets.MemoryToolDelta(
                    memory_text=details.memory_text,
                    operation=details.operation.value,
                    memory_id=details.memory_id,
                    index=details.index,
                )
            )
        elif isinstance(details, LlmPythonExecutionResult):
            objects.append(
                packets.PythonToolDelta(
                    stdout=details.stdout[len(self._stdout) :]
                    if details.stdout.startswith(self._stdout)
                    else "",
                    stderr=details.stderr[len(self._stderr) :]
                    if details.stderr.startswith(self._stderr)
                    else "",
                    file_ids=[
                        file.file_link.rsplit("/", 1)[-1]
                        for file in details.generated_files
                        if file.file_link not in self._files
                    ],
                )
            )
            self._stdout = details.stdout
            self._stderr = details.stderr
            self._files.update(file.file_link for file in details.generated_files)
        elif isinstance(details, LlmBashExecutionResult):
            objects.append(
                packets.BashToolDelta(
                    stdout=details.stdout,
                    stderr=details.stderr,
                    exit_code=details.exit_code,
                    timed_out=details.timed_out,
                )
            )
        elif isinstance(details, FinalImageGenerationResponse):
            objects.append(
                packets.ImageGenerationFinal(
                    images=[
                        packets.GeneratedImage(
                            file_id=image.file_id,
                            url=image.url,
                            revised_prompt=image.revised_prompt,
                            shape=image.shape,
                        )
                        for image in details.generated_images
                    ]
                )
            )
        elif isinstance(details, CustomToolCallSummary):
            files = (
                details.tool_result
                if isinstance(details.tool_result, CustomToolUserFileSnapshot)
                else None
            )
            data: JsonValue = (
                None
                if isinstance(details.tool_result, CustomToolUserFileSnapshot)
                else details.tool_result
            )
            error = details.error
            objects.append(
                packets.CustomToolDelta(
                    tool_name=details.tool_name,
                    tool_id=self.tool_id,
                    response_type=details.response_type,
                    data=data,
                    file_ids=files.file_ids if files else None,
                    error=packets.CustomToolErrorInfo(
                        is_auth_error=error.is_auth_error,
                        status_code=error.status_code,
                        message=error.message,
                    )
                    if error
                    else None,
                )
            )
        elif isinstance(details, CodingAgentCallResult):
            objects.append(packets.CodingAgentThinkingDelta(content=details.answer))
        elif isinstance(details, ResearchAgentCallResult):
            if not self.has_child_output:
                nested = self.placement.model_copy(update={"sub_turn_index": 0})
                return [
                    packets.Packet(placement=nested, obj=obj)
                    for obj in [
                        packets.IntermediateReportStart(),
                        packets.IntermediateReportDelta(
                            content=details.intermediate_report
                        ),
                        packets.IntermediateReportCitedDocs(
                            cited_docs=list(details.citation_mapping.values())
                        ),
                        packets.SectionEnd(),
                    ]
                ]
        elif content and self.call.name not in {
            SearchTool.NAME,
            WebSearchTool.NAME,
            OpenURLTool.NAME,
            ImageGenerationTool.NAME,
            MemoryTool.NAME,
        }:
            objects.append(
                packets.CustomToolDelta(
                    tool_name=self.call.name,
                    tool_id=self.tool_id,
                    response_type="text",
                    data=content,
                )
            )
        self._last_details = details
        return [packets.Packet(placement=self.placement, obj=obj) for obj in objects]

    def complete(self, result: ToolResult | None) -> list[packets.Packet]:
        if result is not None and isinstance(result.details, CodingAgentCallResult):
            output = [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CodingAgentFinal(answer=result.details.answer),
                )
            ]
        else:
            output = (
                self.update(result.details, result.text) if result is not None else []
            )
        if self.call.name == MemoryTool.NAME and result is not None and result.is_error:
            output.append(
                packets.Packet(
                    placement=self.placement, obj=packets.MemoryToolNoAccess()
                )
            )
        output.append(
            packets.Packet(placement=self.placement, obj=packets.SectionEnd())
        )
        return output
