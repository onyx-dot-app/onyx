"""Translate shared messages and tool results into chat browser packets."""

from collections.abc import Mapping

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from typing_extensions import override

from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import CitationMode, MessageRendering, PresentationMode
from onyx.chat.response import thinking_tool_text, tool_arguments_for_display
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.tool_definitions import (
    BASH_TOOL_NAME,
    CODING_AGENT_TOOL_NAME,
    GENERATE_ANSWER_TOOL_NAME,
)
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
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
from onyx.tools.constants import (
    CODE_MODE_TOOL_NAME,
    WAIT_CODE_TOOL_NAME,
)
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
    PythonExecutionDelta,
    ToolExecutionError,
    ToolExecutionException,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CellWindow,
    CodeModeCall,
    CodeModeCallFinished,
    CodeModeCallProgress,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
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
from onyx.utils.logger import setup_logger
from onyx.utils.streaming_json import appended_text, parse_partial_object

HIDDEN_TOOLS = frozenset(
    {
        GENERATE_PLAN_TOOL_NAME,
        GENERATE_REPORT_TOOL_NAME,
        GENERATE_ANSWER_TOOL_NAME,
        THINK_TOOL_NAME,
    }
)

# Tools whose code argument streams to the browser while the model writes it.
CODE_ARGUMENT_TOOLS = frozenset({PythonTool.NAME, CODE_MODE_TOOL_NAME})
# Tools whose calls observe a code mode cell; each call renders as one code mode card.
CODE_MODE_TOOL_NAMES = frozenset({CODE_MODE_TOOL_NAME, WAIT_CODE_TOOL_NAME})

_STRING = TypeAdapter(str)
_INT = TypeAdapter(int)
_STRINGS = TypeAdapter(list[str])
logger = setup_logger()


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
        self._last_tool_placement: Placement | None = None
        self._argument_streams: dict[int, ToolCall] = {}
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
        return bool(self.answer)

    def _append(self, text: str, *, thinking: bool = False) -> list[packets.Packet]:
        if not text or self.settings.mode == PresentationMode.SILENT:
            return []
        # Tool tabs cannot span an intervening text or reasoning section.
        self._last_tool_placement = None
        if self.settings.mode == PresentationMode.CODING_THINKING or (
            thinking and self.settings.mode == PresentationMode.CODING_ANSWER
        ):
            if self.parent is None:
                raise ValueError("Coding output requires a parent tool placement")
            if thinking:
                self.reasoning += text
            else:
                self.answer += text
            if self._answer_placement is None:
                self._answer_placement = self.layout.next_section(self.parent)
            return [
                packets.Packet(
                    placement=self._answer_placement,
                    obj=packets.CodingAgentThinkingDelta(content=text),
                )
            ]
        if thinking:
            self.reasoning += text
            result = []
            if self._reasoning_placement is None:
                result.extend(self._close_answer())
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
        if self.settings.mode == PresentationMode.CODING_ANSWER:
            # The parent tool publishes the final answer in CodingAgentFinal.
            return []
        self.answer += text
        result = []
        if self._answer_placement is None:
            result.extend(self._close_reasoning())
            # Research reports belong to the parent card, not a nested tool section.
            self._answer_placement = (
                self.parent
                if self.settings.mode == PresentationMode.REPORT
                and self.parent is not None
                else self.layout.next_section(self.parent)
            )
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
        citations = []
        for value in self.citation_processor.process_token(text):
            if isinstance(value, str):
                result.extend(self._append(value))
            else:
                self.citations.append(value)
                citations.append(value)
        # Citation metadata can precede the first answer text in the processor.
        if self._answer_placement is not None:
            result.extend(
                packets.Packet(placement=self._answer_placement, obj=value)
                for value in citations
            )
        return result

    def tool_placement(self, call_id: str) -> Placement:
        if call_id not in self.tool_placements:
            previous = self._last_tool_placement
            placement = (
                previous.model_copy(update={"tab_index": previous.tab_index + 1})
                if previous is not None and self.parent is None
                else self.layout.next_section(self.parent)
            )
            self.tool_placements[call_id] = placement
            self._last_tool_placement = placement
        return self.tool_placements[call_id]

    def consume(self, event: GenerationContentEvent) -> list[packets.Packet]:
        if isinstance(event, TextDeltaEvent):
            self._raw_text += event.text
            return self._content(event.text)
        if isinstance(event, ThinkingDeltaEvent):
            self._raw_thinking += event.text
            return self._append(event.text, thinking=True)
        if isinstance(event, ToolCallStartEvent):
            if (
                event.tool_name in CODE_ARGUMENT_TOOLS
                or event.tool_name == self.settings.think_tool
            ):
                self._argument_streams[event.content_index] = ToolCall(
                    id=event.tool_call_id,
                    name=event.tool_name,
                    arguments={},
                    raw_arguments="",
                    arguments_complete=False,
                )
            if (
                event.tool_name == self.settings.think_tool
                or event.tool_name in HIDDEN_TOOLS
            ):
                return []
            result = self._close_answer()
            result.extend(self._close_reasoning())
            self.tool_placement(event.tool_call_id)
            return result
        call = self._argument_streams.get(event.content_index)
        if call is None:
            return []
        if isinstance(event, ToolCallDeltaEvent):
            call.raw_arguments = (call.raw_arguments or "") + event.arguments_delta
            try:
                arguments = parse_partial_object(call.raw_arguments)
            except ValueError:
                logger.debug(
                    "Tool arguments cannot be parsed incrementally", exc_info=True
                )
                del self._argument_streams[event.content_index]
                return []
        else:
            del self._argument_streams[event.content_index]
            arguments = event.tool_call.arguments
        deltas = appended_text(call.arguments, arguments)
        call.arguments = arguments
        if call.name == self.settings.think_tool:
            text = deltas.get("reasoning", "")
            self._raw_thinking += text
            return self._append(text, thinking=True)
        if not deltas:
            return []
        return [
            packets.Packet(
                placement=self.tool_placement(call.id),
                obj=packets.ToolCallArgumentDelta(
                    tool_type=call.name, argument_deltas=deltas
                ),
            )
        ]

    def complete(self, message: AssistantMessage) -> list[packets.Packet]:
        if self._finished:
            return []
        # Nonstreaming providers and interrupted streams can deliver a final suffix.
        text = "".join(
            block.text for block in message.content if isinstance(block, TextContent)
        )
        thinking_by_index: dict[int, str] = {}
        for index, block in enumerate(message.content):
            if isinstance(block, ThinkingContent):
                thinking_by_index[index] = block.text
            elif isinstance(block, ToolCall) and block.name == self.settings.think_tool:
                thinking_by_index[index] = thinking_tool_text(block)
        thinking = "".join(thinking_by_index.values())
        result = []
        text_chars_to_skip = (
            len(self._raw_text) if text.startswith(self._raw_text) else len(text)
        )
        thinking_chars_to_skip = (
            len(self._raw_thinking)
            if thinking.startswith(self._raw_thinking)
            else len(thinking)
        )
        parts: list[str] = []
        pending_thinking = False

        def flush_content() -> None:
            if not parts:
                return
            content = "".join(parts)
            parts.clear()
            result.extend(
                self._append(content, thinking=True)
                if pending_thinking
                else self._content(content)
            )

        # Batch adjacent output without moving it across thinking or tool boundaries.
        for index, block in enumerate(message.content):
            if isinstance(block, TextContent):
                content = block.text[text_chars_to_skip:]
                text_chars_to_skip = max(0, text_chars_to_skip - len(block.text))
                is_thinking = False
            elif index in thinking_by_index:
                thinking_text = thinking_by_index[index]
                content = thinking_text[thinking_chars_to_skip:]
                thinking_chars_to_skip = max(
                    0, thinking_chars_to_skip - len(thinking_text)
                )
                is_thinking = True
            else:
                flush_content()
                if (
                    isinstance(block, ToolCall)
                    and block.name not in HIDDEN_TOOLS
                    and block.id not in self.tool_placements
                ):
                    result.extend(self._close_answer())
                    result.extend(self._close_reasoning())
                    self.tool_placement(block.id)
                continue
            if not content:
                continue
            if is_thinking != pending_thinking:
                flush_content()
                pending_thinking = is_thinking
            parts.append(content)
        flush_content()
        result.extend(self.finish())
        if (
            text
            and not self.answer
            and not self.reasoning
            and self.settings.citation_mode != CitationMode.REMOVE
        ):
            result.extend(self._append(text))
            if self._answer_placement is not None:
                result.append(
                    packets.Packet(
                        placement=self._answer_placement, obj=packets.SectionEnd()
                    )
                )
        return result

    def _close_answer(self) -> list[packets.Packet]:
        # Reports and coding output share their parent card across content blocks.
        if self.settings.mode not in (PresentationMode.ANSWER, PresentationMode.PLAN):
            return []
        result = self._content(None)
        if self._answer_placement is not None:
            result.append(
                packets.Packet(
                    placement=self._answer_placement, obj=packets.SectionEnd()
                )
            )
            self._answer_placement = None
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
                            cited_docs=list(
                                self.citation_processor.get_seen_citations().values()
                            )
                            if self.citation_processor is not None
                            else []
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
        self,
        call: ToolCall,
        placement: Placement,
        tool_id: int | None = None,
        display_name: str | None = None,
    ) -> None:
        self.call = call
        self.placement = placement
        self.tool_id = tool_id
        # The tool's own display name; calls of tools without one show their name.
        self.display_name = display_name or call.name
        self._queries: set[str] = set()
        self._documents: set[str] = set()
        self._last_details: BaseModel | None = None
        self.has_child_output = False
        self._has_python_output = False
        self._files: set[str] = set()
        self._started = False
        self._finished = False

    def start(self) -> list[packets.Packet]:
        if self._started:
            return []
        self._started = True
        name = self.call.name
        args = tool_arguments_for_display(self.call)
        objects: list[packets.PacketObj]
        try:
            objects = self._start_objects(args)
        except ValidationError:
            objects = []
            logger.debug(
                "Tool arguments cannot use the specialized display", exc_info=True
            )
        if not objects:
            objects = [
                packets.CustomToolStart(
                    tool_name=name,
                    display_name=self.display_name,
                    tool_id=self.tool_id,
                ),
                packets.CustomToolArgs(
                    tool_name=name,
                    tool_args={
                        key: value for key, value in args.items() if key != REQUEST_BODY
                    },
                ),
            ]
        if INTEGRATION_TESTS_MODE:
            objects.insert(
                0,
                packets.ToolCallDebug(
                    tool_call_id=self.call.id,
                    tool_name=name,
                    tool_args={
                        key: value for key, value in args.items() if key != REQUEST_BODY
                    },
                ),
            )
        return [packets.Packet(placement=self.placement, obj=obj) for obj in objects]

    def _start_objects(self, args: dict[str, JsonValue]) -> list[packets.PacketObj]:
        """The tool's own start packets; empty for the generic tool display.

        Raises ValidationError when the arguments do not fit the tool's display.
        """
        name = self.call.name
        objects: list[packets.PacketObj] = []
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
        return objects

    def update(
        self, details: BaseModel | None, content: str = ""
    ) -> list[packets.Packet]:
        """Render progress; progress after the call completes is dropped."""
        if self._finished:
            return []
        return self._detail_packets(details, content)

    def _detail_packets(
        self, details: BaseModel | None, content: str
    ) -> list[packets.Packet]:
        """Render result details; content already rendered is skipped."""
        objects: list[packets.PacketObj] = []
        if isinstance(details, PythonExecutionDelta):
            self._has_python_output = True
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.PythonToolDelta(
                        stdout=details.stdout, stderr=details.stderr
                    ),
                )
            ]
        if isinstance(details, SearchDocsResponse):
            docs = (
                details.displayed_docs
                if details.displayed_docs is not None
                else details.search_docs
            )
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
            stderr = "" if self._has_python_output else details.stderr
            if details.exit_code == -1 and details.error:
                stderr = details.error
            objects.append(
                packets.PythonToolDelta(
                    # Live output is complete; the saved result may be truncated.
                    stdout="" if self._has_python_output else details.stdout,
                    stderr=stderr,
                    file_ids=[
                        file.file_link.rsplit("/", 1)[-1]
                        for file in details.generated_files
                        if file.file_link not in self._files
                    ],
                )
            )
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
                    display_name=self.display_name,
                    tool_id=self.tool_id,
                    response_type=details.response_type,
                    data=data,
                    file_ids=files.file_ids if files else None,
                    error=packets.CustomToolErrorInfo(
                        is_auth_error=error.is_auth_error,
                        is_unreachable=error.is_unreachable,
                        status_code=error.status_code,
                        message=error.message,
                    )
                    if error
                    else None,
                )
            )
        elif isinstance(details, CodingAgentCallResult):
            # Child message events carry thinking; completion carries the final answer.
            return []
        elif isinstance(details, ResearchAgentCallResult):
            if not self.has_child_output:
                objects.extend(
                    [
                        packets.IntermediateReportStart(),
                        packets.IntermediateReportDelta(
                            content=details.intermediate_report
                        ),
                        packets.IntermediateReportCitedDocs(
                            cited_docs=list(details.citation_mapping.values())
                        ),
                    ]
                )
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
                    display_name=self.display_name,
                    tool_id=self.tool_id,
                    response_type="text",
                    data=content,
                )
            )
        self._last_details = details
        return [packets.Packet(placement=self.placement, obj=obj) for obj in objects]

    def complete(self, result: ToolResult | None) -> list[packets.Packet]:
        """Render the result and end the call's section.

        The part of the result that an amendment added follows the section end,
        as it does when the amendment arrives live.
        """
        if self._finished:
            return []
        output = self.start()
        output.extend(self._result_packets(result))
        self._finished = True
        if result is not None and isinstance(result.details, ToolExecutionError):
            output.append(
                packets.Packet(
                    placement=self.placement,
                    obj=packets.PacketException(
                        exception=ToolExecutionException(result.details.message)
                    ),
                )
            )
        output.append(
            packets.Packet(placement=self.placement, obj=packets.SectionEnd())
        )
        if result is not None:
            output.extend(self._amendment_packets(result))
        return output

    def _result_packets(self, result: ToolResult | None) -> list[packets.Packet]:
        """The packets of a final result of the call, before its section end."""
        if result is not None and isinstance(result.details, CodingAgentCallResult):
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CodingAgentFinal(answer=result.details.answer),
                )
            ]
        if result is not None:
            return self._detail_packets(
                result.details, "" if result.is_error else result.text
            )
        return []

    def amend(self, result: ToolResult) -> list[packets.Packet]:
        """Render the result that a release hook set for the call.

        An ended call renders only what the amendment added. Any other call
        completes with the result.
        """
        if not self._finished:
            return self.complete(result)
        return self._amendment_packets(result)

    def _amendment_packets(self, result: ToolResult) -> list[packets.Packet]:  # noqa: ARG002
        """What a release hook added to the result after the call ended.

        The generic display cannot tell an amendment apart from the result it
        replaces, so it adds nothing; the saved result shows on replay.
        """
        return []


def _stored_keys(window: CellWindow) -> list[str] | None:
    commit = window.commit
    if commit is None:
        return None
    return [key for key, value in commit.writes.items() if value is not None] or None


class CodeModeRenderer(ToolRenderer):
    """One observation of a cell. Each nested call renders with its tool's own
    renderer, at `sub_turn_index = call.index` of the card's placement.

    Nested call identity: a cell reports each call in every observation until
    the call ends, so one call can stream its start packet several times, under
    the placement of each observation. Clients identify a call by its cell and
    its `sub_turn_index`, and show the latest report. The cell id is on
    `CodeModeStart.cell_id` (wait_code) or on the final `CodeModeDelta.cell_id`
    (execute_code). The cell's closing record follows the section end of its
    last observation, under the same placement.
    """

    def __init__(
        self,
        call: ToolCall,
        placement: Placement,
        tool_id: int | None = None,
        display_name: str | None = None,
    ) -> None:
        super().__init__(call, placement, tool_id, display_name)
        self._children: dict[int, ToolRenderer] = {}
        self._stdout = ""

    def _start_objects(self, args: dict[str, JsonValue]) -> list[packets.PacketObj]:
        if self.call.name == WAIT_CODE_TOOL_NAME:
            return [
                packets.CodeModeStart(
                    code="",
                    cell_id=_INT.validate_python(args.get("cell_id")),
                    observation=1,
                )
            ]
        return [
            packets.CodeModeStart(code=_STRING.validate_python(args.get("code", "")))
        ]

    @override
    def _detail_packets(
        self, details: BaseModel | None, content: str
    ) -> list[packets.Packet]:
        if isinstance(details, CodeModeStdout):
            if not details.text:
                return []
            self._stdout += details.text
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CodeModeDelta(stdout=details.text),
                )
            ]
        if isinstance(details, CodeModeCallStarted):
            return self._child(details.call).start()
        if isinstance(details, CodeModeCallProgress):
            child = self._children.get(details.index)
            return child.update(details.details, details.content) if child else []
        if isinstance(details, CodeModeCallFinished):
            return self._complete_child(details.call)
        return []

    def _child(self, call: CodeModeCall) -> ToolRenderer:
        child = self._children.get(call.index)
        if child is None:
            child = ToolRenderer(
                ToolCall(
                    id=call.id,
                    name=call.tool_name,
                    arguments=call.arguments,
                ),
                self.placement.model_copy(update={"sub_turn_index": call.index}),
                call.tool_id,
                call.display_name,
            )
            self._children[call.index] = child
        return child

    def _complete_child(self, call: CodeModeCall) -> list[packets.Packet]:
        return self._child(call).complete(call.as_result())

    def _complete_open_children(self) -> list[packets.Packet]:
        return [
            packet
            for index in sorted(self._children)
            for packet in self._children[index].complete(None)
        ]

    def _result_packets(self, result: ToolResult | None) -> list[packets.Packet]:
        """Close nested calls, then send the program output and the final status.

        Replay has no progress events, so the saved calls render here.
        """
        details = result.details if result is not None else None
        execution = details if isinstance(details, CodeModeExecutionResult) else None
        if execution is None:
            output = self._complete_open_children()
            if result is not None and result.is_error:
                final = packets.CodeModeDelta(error=result.text, status="failed")
            elif result is None:
                # The response ended before the call saved a result.
                final = packets.CodeModeDelta(
                    status="cancelled", tool_call_count=len(self._children)
                )
            else:
                return output
            output.append(packets.Packet(placement=self.placement, obj=final))
            return output
        # Calls still running when the observation ended stay open; a later
        # observation or the cell's closing record reports how they ended.
        output = [
            packet
            for call in execution.calls
            for packet in (
                self._child(call).start()
                if call.state == "running"
                else self._complete_child(call)
            )
        ]
        running = {call.index for call in execution.calls if call.state == "running"}
        output.extend(
            packet
            for index in sorted(self._children)
            if index not in running
            for packet in self._children[index].complete(None)
        )
        # Live output stops at the output limit; the saved output keeps the start
        # and the end. The final delta makes live output match replay.
        replace = bool(self._stdout) and self._stdout != execution.stdout
        output.append(
            packets.Packet(
                placement=self.placement,
                obj=packets.CodeModeDelta(
                    stdout=execution.stdout if replace or not self._stdout else "",
                    replace_stdout=replace,
                    result=execution.result,
                    error=execution.error,
                    status=execution.status,
                    duration_seconds=execution.duration_seconds,
                    tool_call_count=execution.tool_call_count,
                    stored_keys=_stored_keys(execution),
                    cell_id=execution.cell_id,
                    observation=execution.observation,
                ),
            )
        )
        return output

    @override
    def _amendment_packets(self, result: ToolResult) -> list[packets.Packet]:
        """The cell's closing record: what the cell did after the observation, up
        to the end of the response."""
        details = result.details
        closing = (
            details.closing if isinstance(details, CodeModeExecutionResult) else None
        )
        if closing is None:
            return []
        output = [
            packet for call in closing.calls for packet in self._complete_child(call)
        ]
        output.extend(self._complete_open_children())
        if closing.stdout:
            output.append(
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CodeModeDelta(stdout=closing.stdout),
                )
            )
        output.append(
            packets.Packet(
                placement=self.placement,
                obj=packets.CodeModeDelta(
                    result=closing.result,
                    error=closing.error,
                    status=closing.status,
                    tool_call_count=closing.tool_call_count,
                    stored_keys=_stored_keys(closing),
                    response_ended=True,
                ),
            )
        )
        return output


def tool_renderer(
    call: ToolCall,
    placement: Placement,
    tool_id: int | None = None,
    display_name: str | None = None,
) -> ToolRenderer:
    """The renderer of a tool call: a code mode card, or the generic tool display."""
    renderer = CodeModeRenderer if call.name in CODE_MODE_TOOL_NAMES else ToolRenderer
    return renderer(call, placement, tool_id, display_name)
