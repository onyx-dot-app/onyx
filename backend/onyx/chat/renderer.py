"""Translate shared messages and tool results into chat browser packets."""

from collections.abc import Mapping
from time import monotonic
from typing import Literal, NamedTuple, TypeGuard

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from typing_extensions import override

from onyx.agents.events import (
    InputEndedEvent,
    InputRequiredEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.tools import HumanToolAnswer, InputDecision
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import (
    CitationMode,
    MessageRendering,
    PresentationMode,
    RunDocuments,
    ToolApprovalDenial,
)
from onyx.chat.response import tool_arguments_for_display
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.context.search.models import SearchDocsResponse
from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationContentEvent,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultFields,
)
from onyx.server.features.build.sandbox.models import (
    ExecOutputDelta as SandboxOutputDelta,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.constants import WRITE_STDIN_TOOL_NAME
from onyx.tools.interface import parse_tool_arguments
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    FileReadResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
    PythonExecutionDelta,
    ToolCallException,
    ToolExecutionError,
    ToolExecutionException,
)
from onyx.tools.tool_implementations.api_app.openapi_parsing import REQUEST_BODY
from onyx.tools.tool_implementations.code_mode.models import (
    CellWindow,
    CodeModeCall,
    CodeModeCallFinished,
    CodeModeCallProgress,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
)
from onyx.tools.tool_implementations.code_mode.shapes import (
    CODE_MODE_TOOL_NAMES,
    RUN_TOOL_NAMES,
    WAIT_TOOL_NAMES,
)
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OPEN_URL_TOOL_NAMES
from onyx.tools.tool_implementations.postgres.postgres_tool import PostgresTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.question.models import QuestionToolDetails
from onyx.tools.tool_implementations.question.shapes import (
    QUESTION_SHAPES_BY_NAME,
    QUESTION_TOOL_NAMES,
)
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_PUBLISH_PATHS,
    ApplyPatchResult,
    CommandApprovalRequest,
    CommandApprovalResolved,
    FileToolName,
    PublishedFiles,
    PublishedFileView,
    PublishFileArgument,
    SandboxExecResult,
    SpilledOutput,
)
from onyx.tools.tool_implementations.sandbox.patch import (
    HUNK_HEADER_MARKERS,
    display_patch,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ApplyPatchTool,
    ArtifactTool,
    EditTool,
    LibraryCreateLibraryFileTool,
    LibraryReplaceLibraryFileTool,
    WriteTool,
)
from onyx.tools.tool_implementations.sandbox.shapes import (
    SHELL_SHAPES_BY_NAME,
    SHELL_TOOL_NAMES,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger
from onyx.utils.streaming_json import appended_text, parse_partial_object

HIDDEN_TOOLS = frozenset(
    {
        GENERATE_PLAN_TOOL_NAME,
        GENERATE_REPORT_TOOL_NAME,
    }
)

# The card's note between the head and the tail of a spilled result.
SPILLED_OUTPUT_NOTE = "Large output: the full result was saved to the sandbox."
# Tools whose code argument streams to the browser while the model writes it.
CODE_ARGUMENT_TOOLS = frozenset({PythonTool.NAME, *RUN_TOOL_NAMES})
# Tools whose prompt argument streams to the browser while the model writes it.
PROMPT_ARGUMENT_TOOLS = frozenset({ImageGenerationTool.NAME})


class FileToolArguments(NamedTuple):
    # The argument that holds the tool's text.
    text: str
    # The argument that names the file; None when the text names the files.
    path: str | None


# The file tools (FileToolName) and their arguments. Their calls render as a
# patch card and end with apply_patch_end.
FILE_TOOL_ARGUMENTS: dict[FileToolName, FileToolArguments] = {
    ApplyPatchTool.NAME: FileToolArguments(text="input", path=None),
    EditTool.NAME: FileToolArguments(text="new_string", path="file_path"),
    WriteTool.NAME: FileToolArguments(text="content", path="file_path"),
}
OwnEndPacket = (
    type[packets.ExecEnd] | type[packets.ApplyPatchEnd] | type[packets.PublishFilesEnd]
)
# Tools whose calls end with their own end packet, and its type; a failed call
# ends with that packet's error. Each call of these tools sends its own start
# packet too, so the end never lands on a generic card. A call with the publish
# card (publish_card_files) ends with PublishFilesEnd.
OWN_END_PACKETS: dict[str, OwnEndPacket] = {
    **dict.fromkeys(SHELL_TOOL_NAMES, packets.ExecEnd),
    WRITE_STDIN_TOOL_NAME: packets.ExecEnd,
    **dict.fromkeys(FILE_TOOL_ARGUMENTS, packets.ApplyPatchEnd),
}
# The arguments that name the file, or the files, of each tool's publish.
_PUBLISH_PATH_ARGUMENTS: dict[str, tuple[str, str | None]] = {
    LibraryCreateLibraryFileTool.NAME: ("file", "files"),
    LibraryReplaceLibraryFileTool.NAME: ("file", None),
    ArtifactTool.NAME: ARTIFACT_PUBLISH_PATHS,
}
# The shortest time between two reports of a call's streamed arguments.
# Between reports the renderer only collects fragments, so it parses the
# arguments at most this often, not once per fragment.
ARGUMENT_REPORT_INTERVAL_SECONDS = 0.25

_STRING = TypeAdapter(str)
_OPTIONAL_STRING = TypeAdapter(str | None)
_INT = TypeAdapter(int)
_STRINGS = TypeAdapter(list[str])
logger = setup_logger()


def publish_card_files(
    name: str, args: dict[str, JsonValue]
) -> list[PublishFileArgument] | None:
    """The files that a call of tool `name` asks to publish, as the model
    wrote them, when the call shows the publish card; None for any other
    call. Raises ValidationError when the arguments do not fit the card."""
    keys = _PUBLISH_PATH_ARGUMENTS.get(name)
    # A missing or null action is a publish, as parse_tool_arguments reads
    # it. The artifact tool's publish with a path copies a stored file (an
    # update), which shows the generic card.
    if keys is None or (
        name == ArtifactTool.NAME
        and (
            args.get("action") not in (None, "publish") or args.get("path") is not None
        )
    ):
        return None
    one, several = keys
    path = args.get(one)
    title = _OPTIONAL_STRING.validate_python(args.get("title"))
    return [
        PublishFileArgument(path=path, title=title)
        for path in _STRINGS.validate_python(
            [path] if path is not None else (several and args.get(several)) or []
        )
    ]


def _spilled_card_text(spilled: SpilledOutput) -> str:
    """What the user's card shows of a spilled result: the head, a plain
    note, and the tail; never the model's instructions."""
    return f"{spilled.head}\n\n[{SPILLED_OUTPUT_NOTE}]\n\n{spilled.tail}"


def _string_argument(arguments: Mapping[str, JsonValue], key: str) -> str:
    """A string argument; a missing or wrong-typed value reads as empty."""
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def is_file_tool(name: str) -> TypeGuard[FileToolName]:
    return name in FILE_TOOL_ARGUMENTS


def file_tool_progress(
    tool_name: FileToolName, arguments: dict[str, JsonValue], complete: bool
) -> packets.FileToolProgress:
    """The files a file tool call's arguments name, parsed so far or `complete`.

    A partial parse can cut off its last string, so a patch header counts once
    its line ends, and the path argument once a later key follows it.
    """
    text_key, path_key = FILE_TOOL_ARGUMENTS[tool_name]
    if path_key is None:
        lines = _string_argument(arguments, text_key).split("\n")
        headers = (line.strip() for line in (lines if complete else lines[:-1]))
        # Two hunks of one file name it once.
        paths = list(
            dict.fromkeys(
                header[len(marker) :].strip()
                for header in headers
                for marker in HUNK_HEADER_MARKERS
                if header.startswith(marker)
            )
        )
    else:
        path = _string_argument(arguments, path_key)
        whole = complete or next(reversed(arguments), None) != path_key
        paths = [path] if path and whole else []
    return packets.FileToolProgress(tool_name=tool_name, paths=paths)


class _ArgumentStream:
    """A tool call whose arguments the browser sees while the model writes them.

    It holds the fragments between reports and reports at most once per
    ARGUMENT_REPORT_INTERVAL_SECONDS. A report is what changed since the last
    one: the appended text of each string argument, or the files that a file
    tool call names, once they change.
    """

    def __init__(
        self,
        call_id: str,
        name: str,
        report: Literal["text"] | FileToolName,
    ) -> None:
        self.id = call_id
        self.name = name
        # How the arguments show: as their text (code or a prompt), or as a
        # file tool's progress.
        self.report = report
        # The arguments text of the last report, and what it parsed to.
        self.reported = ""
        self.arguments: dict[str, JsonValue] = {}
        # The fragments that arrived after the last report.
        self.held: list[str] = []
        self.reported_at = float("-inf")
        # The last progress a file tool call sent; it sends a new one only
        # when its files change.
        self.progress: packets.FileToolProgress | None = None
        # Set when the arguments cannot be the start of a JSON object.
        self.stopped = False

    def add(self, fragment: str) -> dict[str, str] | packets.FileToolProgress | None:
        """Hold a fragment; report the held fragments once the interval passed."""
        if self.stopped:
            return None
        self.held.append(fragment)
        if monotonic() - self.reported_at < ARGUMENT_REPORT_INTERVAL_SECONDS:
            return None
        return self.flush()

    def flush(self) -> dict[str, str] | packets.FileToolProgress | None:
        """Report the arguments streamed so far."""
        if self.stopped:
            return None
        self.reported_at = monotonic()
        self.reported += "".join(self.held)
        self.held.clear()
        try:
            arguments = parse_partial_object(self.reported)
        except ValueError:
            logger.debug("Tool arguments cannot be parsed incrementally", exc_info=True)
            self.stopped = True
            return None
        return self._update(arguments, complete=False)

    def end(self, call: ToolCall) -> dict[str, str] | packets.FileToolProgress | None:
        """Report the call's final arguments. An invalid call's final arguments
        are empty, so it reports what streamed."""
        if call.argument_error is not None:
            return self.flush()
        if self.stopped:
            return None
        return self._update(call.arguments, complete=True)

    def _update(
        self, arguments: dict[str, JsonValue], complete: bool
    ) -> dict[str, str] | packets.FileToolProgress | None:
        previous, self.arguments = self.arguments, arguments
        if is_file_tool(self.report):
            progress = file_tool_progress(self.report, arguments, complete)
            if progress == self.progress:
                return None
            self.progress = progress
            return progress
        return appended_text(previous, arguments) or None


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
        documents: RunDocuments,
        layout: ResponseLayout,
        parent: Placement | None = None,
    ) -> None:
        """`documents` are those of the message's run up to and including
        the message's step."""
        self.settings = settings
        self.layout = layout
        self.parent = parent
        self.answer = ""
        self.reasoning = ""
        self.citations: list[packets.CitationInfo] = []
        self.documents = list(documents.shown.values())
        self._answer_placement: Placement | None = None
        self._reasoning_placement: Placement | None = None
        self._raw_text = ""
        self._raw_thinking = ""
        self._finished = False
        self.tool_placements: dict[str, Placement] = {}
        self._last_tool_placement: Placement | None = None
        self._argument_streams: dict[int, _ArgumentStream] = {}
        # The content blocks that the message's events have reached.
        self._block_count = 0
        self.citation_processor = (
            DynamicCitationProcessor(citation_mode=settings.citation_mode)
            if settings.citation_mode is not None
            else None
        )
        if self.citation_processor:
            self.citation_processor.update_citation_mapping(documents.citations)

    @property
    def answer_started(self) -> bool:
        return bool(self.answer)

    def _append(self, text: str, *, thinking: bool = False) -> list[packets.Packet]:
        if not text or self.settings.mode == PresentationMode.SILENT:
            return []
        # Tool tabs cannot span an intervening text or reasoning section.
        self._last_tool_placement = None
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
        if self.settings.mode == PresentationMode.RESEARCH:
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
        # A new content block: the held fragments of the open calls report
        # before it, so live sections come in the replay order.
        result = self._report_held() if event.content_index >= self._block_count else []
        self._block_count = max(self._block_count, event.content_index + 1)
        if isinstance(event, TextDeltaEvent):
            self._raw_text += event.text
            return result + self._content(event.text)
        if isinstance(event, ThinkingDeltaEvent):
            self._raw_thinking += event.text
            return result + self._append(event.text, thinking=True)
        if isinstance(event, ToolCallStartEvent):
            report: Literal["text"] | FileToolName | None = (
                "text"
                if event.tool_name in CODE_ARGUMENT_TOOLS
                or event.tool_name in PROMPT_ARGUMENT_TOOLS
                else event.tool_name
                if is_file_tool(event.tool_name)
                else None
            )
            if report is not None:
                self._argument_streams[event.content_index] = _ArgumentStream(
                    event.tool_call_id, event.tool_name, report
                )
            if event.tool_name in HIDDEN_TOOLS:
                return result
            result.extend(self._close_answer())
            result.extend(self._close_reasoning())
            self.tool_placement(event.tool_call_id)
            return result
        stream = self._argument_streams.get(event.content_index)
        if stream is None:
            return []
        if isinstance(event, ToolCallEndEvent):
            del self._argument_streams[event.content_index]
            return self._report(stream, stream.end(event.tool_call))
        return self._report(stream, stream.add(event.arguments_delta))

    def _report(
        self,
        stream: _ArgumentStream,
        report: dict[str, str] | packets.FileToolProgress | None,
    ) -> list[packets.Packet]:
        """The packets that show a report of a call's streamed arguments."""
        obj: packets.PacketObj
        if report is None:
            return []
        if isinstance(report, packets.FileToolProgress):
            obj = report
        else:
            obj = packets.ToolCallArgumentDelta(
                tool_type=stream.name, argument_deltas=report
            )
        return [packets.Packet(placement=self.tool_placement(stream.id), obj=obj)]

    def _report_held(self) -> list[packets.Packet]:
        """Report the fragments that each open stream holds."""
        return [
            packet
            for stream in list(self._argument_streams.values())
            if stream.held
            for packet in self._report(stream, stream.flush())
        ]

    def _flush_arguments(self) -> list[packets.Packet]:
        """Report the fragments that each open stream holds and close the
        streams: an interrupted call has no end event."""
        result = self._report_held()
        self._argument_streams.clear()
        return result

    def complete(self, message: AssistantMessage) -> list[packets.Packet]:
        if self._finished:
            return []
        # Nonstreaming providers and interrupted streams can deliver a final suffix.
        text = "".join(
            block.text for block in message.content if isinstance(block, TextContent)
        )
        thinking = message.thinking
        result = self._flush_arguments()
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
        for block in message.content:
            if isinstance(block, TextContent):
                content = block.text[text_chars_to_skip:]
                text_chars_to_skip = max(0, text_chars_to_skip - len(block.text))
                is_thinking = False
            elif isinstance(block, ThinkingContent):
                thinking_text = block.text
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
        result = self._flush_arguments()
        result.extend(self._content(None))
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


def approval_outcome(answer: HumanToolAnswer | None) -> packets.ToolApprovalOutcome:
    """How an approval request ended, from the answer it gave its call; a
    request without an answer stopped waiting."""
    if answer is None:
        return "cancelled"
    if answer.standing:
        return "approved_for_chat"
    if answer.decision == InputDecision.APPROVE:
        return "approved"
    denial = answer.result.metadata if answer.result else None
    return denial.outcome if isinstance(denial, ToolApprovalDenial) else "rejected"


_ANSWERED_VIA: dict[QuestionAnsweredVia, Literal["card", "message"]] = {
    QuestionAnsweredVia.CARD: "card",
    QuestionAnsweredVia.MESSAGE: "message",
}


def question_resolved(
    request_id: str, answer: HumanToolAnswer | None
) -> packets.ToolQuestionResolved:
    """How a question ended, from the result its answer gave the call; a
    question without an answer stopped waiting."""
    details = answer.result.details if answer and answer.result else None
    if (
        not isinstance(details, QuestionToolDetails)
        or details.outcome != QuestionOutcome.ANSWERED
        or details.answered_via is None
    ):
        return packets.ToolQuestionResolved(
            question_request_id=request_id, outcome="cancelled"
        )
    return packets.ToolQuestionResolved(
        question_request_id=request_id,
        outcome="answered",
        answered_via=_ANSWERED_VIA[details.answered_via],
        answers=details.answers,
        message=details.message,
    )


# The response type of a generic card's call that failed without details.
CUSTOM_TOOL_ERROR_RESPONSE_TYPE = "error"


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
        self.display_name = display_name
        self._queries: set[str] = set()
        self._documents: set[str] = set()
        self._last_details: BaseModel | None = None
        # The content of a result without details that the card shows.
        self._last_content: str | None = None
        self.has_child_output = False
        self._has_python_output = False
        self._files: set[str] = set()
        self._started = False
        self._finished = False
        # The end packet of a failed call, chosen with the start packet.
        self._own_end: OwnEndPacket | None = None
        # The call shows on the generic tool card (CustomToolStart).
        self._generic_display = False
        # An approval request of the call ended without an approval, so its
        # error result is that decision, not a failure.
        self._not_approved = False
        # The command approval cards of the call that wait for a resolution.
        self._open_command_approvals: dict[str, None] = {}

    def consume(
        self,
        event: ToolStartEvent
        | ToolUpdateEvent
        | ToolEndEvent
        | InputRequiredEvent
        | InputEndedEvent,
    ) -> list[packets.Packet]:
        if isinstance(event, ToolStartEvent):
            self.display_name = event.display_name
            return self.start()
        if isinstance(event, ToolUpdateEvent):
            return self.update(event.progress.details, event.progress.content)
        if isinstance(event, ToolEndEvent):
            return self.complete(event.result)
        # Only the requests of the chat's tool approvals have cards
        # (onyx/chat/tool_approvals.py).
        if not event.request.approval:
            return []
        obj: packets.ToolApprovalRequest | packets.ToolApprovalResolved
        if isinstance(event, InputRequiredEvent):
            # A program's call waits inside this call's card.
            call = event.nested_call or self.call
            obj = packets.ToolApprovalRequest(
                approval_id=event.request.request_id,
                tool_call_id=call.id,
                tool_name=call.name,
                display_name=event.request.display_name or call.name,
                arguments=event.request.display_arguments
                if event.request.display_arguments is not None
                else tool_arguments_for_display(call),
                can_approve_for_chat=event.request.can_approve_for_chat,
                app_name=event.request.app_name,
            )
        else:
            obj = self.approval_resolved(
                event.request.request_id, approval_outcome(event.answer)
            )
        return [packets.Packet(placement=self.placement, obj=obj)]

    def approval_resolved(
        self, approval_id: str, outcome: packets.ToolApprovalOutcome
    ) -> packets.ToolApprovalResolved:
        """The end of one of the call's approval requests, live or saved."""
        if outcome not in ("approved", "approved_for_chat"):
            self._not_approved = True
        return packets.ToolApprovalResolved(approval_id=approval_id, outcome=outcome)

    def start(self) -> list[packets.Packet]:
        if self._started:
            return []
        self._started = True
        name = self.call.name
        args = tool_arguments_for_display(self.call)
        objects: list[packets.PacketObj]
        try:
            objects = self._start_objects(args)
        except (ValidationError, ToolCallException):
            logger.debug(
                "Tool arguments cannot use the specialized display", exc_info=True
            )
            # A tool with its own end packet keeps its own card, which then
            # shows empty arguments; the end packet carries the error.
            objects = (
                self._start_objects({})
                if name in OWN_END_PACKETS or publish_card_files(name, {}) is not None
                else []
            )
        self._own_end = (
            packets.PublishFilesEnd
            if any(isinstance(obj, packets.PublishFilesStart) for obj in objects)
            else OWN_END_PACKETS.get(name)
        )
        if not objects:
            self._generic_display = True
            objects = [
                packets.CustomToolStart(
                    tool_name=name,
                    display_name=self.display_name or name,
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

        Raises ValidationError or ToolCallException when the arguments do not
        fit the tool's display.
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
        elif name in OPEN_URL_TOOL_NAMES:
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
        elif name in SHELL_TOOL_NAMES:
            shell = SHELL_SHAPES_BY_NAME[name]
            objects = [
                packets.ExecCommandStart(
                    cmd=_STRING.validate_python(args.get(shell.command_argument, "")),
                    workdir=None
                    if shell.workdir_argument is None
                    else _OPTIONAL_STRING.validate_python(
                        args.get(shell.workdir_argument)
                    ),
                )
            ]
        elif name == WRITE_STDIN_TOOL_NAME:
            # Every shape names the session ID and the characters alike; the
            # card reads only those. Interrupted arguments can lack them,
            # null selects the default as the tool reads it, and models may
            # send the session ID as a number.
            session_id = args.get("session_id")
            objects = [
                packets.WriteStdinStart(
                    session_id=_OPTIONAL_STRING.validate_python(
                        str(session_id) if isinstance(session_id, int) else session_id
                    )
                    or "",
                    chars=_OPTIONAL_STRING.validate_python(args.get("chars")) or "",
                )
            ]
        elif is_file_tool(name):
            text_key, path_key = FILE_TOOL_ARGUMENTS[name]
            patch = _STRING.validate_python(args.get(text_key, ""))
            if path_key is not None:
                path = _STRING.validate_python(args.get(path_key, ""))
                # An edit with an empty old_string creates the file; write's
                # end packet tells an added file from an updated one.
                old = (
                    _STRING.validate_python(args.get("old_string", ""))
                    if name == EditTool.NAME
                    else ""
                )
                # Without a file path the text is not a patch, so the card
                # starts empty.
                patch = display_patch(path, old or None, patch) if path else ""
            objects = [packets.ApplyPatchStart(patch=patch, tool_name=name)]
        elif (files := publish_card_files(name, args)) is not None:
            objects = [
                packets.PublishFilesStart(
                    files=files,
                    description=_OPTIONAL_STRING.validate_python(
                        args.get("description")
                    ),
                )
            ]
        elif name == FileReaderTool.NAME:
            objects = [packets.FileReaderStart()]
        elif name == MemoryTool.NAME:
            objects = [packets.MemoryToolStart()]
        elif name == PostgresTool.NAME:
            objects = [packets.PostgresToolStart(query=args)]
        elif name == ImageGenerationTool.NAME:
            objects = [packets.ImageGenerationToolStart()]
        elif name == RESEARCH_AGENT_TOOL_NAME:
            objects = [
                packets.ResearchAgentStart(
                    research_task=_STRING.validate_python(args.get("task", ""))
                )
            ]
        return objects

    def _search_docs_objects(
        self, details: SearchDocsResponse
    ) -> list[packets.PacketObj]:
        docs = (
            details.displayed_docs
            if details.displayed_docs is not None
            else details.search_docs
        )
        new_docs = [doc for doc in docs if doc.document_id not in self._documents]
        self._documents.update(doc.document_id for doc in docs)
        if self.call.name in OPEN_URL_TOOL_NAMES:
            return (
                [packets.OpenUrlDocuments(documents=new_docs, urls=details.opened_urls)]
                if new_docs
                else []
            )
        if self.call.name == PostgresTool.NAME:
            return (
                [packets.PostgresToolDocuments(documents=new_docs)] if new_docs else []
            )
        objects: list[packets.PacketObj] = []
        queries = [query for query in details.queries if query not in self._queries]
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
        if isinstance(details, CommandApprovalRequest):
            self._open_command_approvals[details.approval_id] = None
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.ToolApprovalRequest(
                        approval_id=details.approval_id,
                        tool_call_id=self.call.id,
                        tool_name=details.action_type,
                        display_name=details.display_name,
                        arguments=details.arguments,
                        can_approve_for_chat=False,
                        can_approve_for_command=details.can_approve_for_command,
                        app_name=details.app_name,
                        expires_at=details.expires_at,
                    ),
                )
            ]
        if isinstance(details, CommandApprovalResolved):
            self._open_command_approvals.pop(details.approval_id, None)
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.ToolApprovalResolved(
                        approval_id=details.approval_id, outcome=details.outcome
                    ),
                )
            ]
        if isinstance(
            details,
            (SandboxOutputDelta, SandboxExecResult, ApplyPatchResult, PublishedFiles),
        ):
            return self._sandbox_packets(details)
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
            objects.extend(self._search_docs_objects(details))
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
            spilled = details.spilled
            data: JsonValue = None
            if spilled is not None:
                data = _spilled_card_text(spilled)
            elif not isinstance(details.tool_result, CustomToolUserFileSnapshot):
                data = details.tool_result
            error = details.error
            objects.append(
                packets.CustomToolDelta(
                    tool_name=details.tool_name,
                    tool_id=self.tool_id,
                    integration_id=details.integration_id,
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
        elif (
            content
            and content != self._last_content
            and self.call.name
            not in {
                SearchTool.NAME,
                WebSearchTool.NAME,
                *OPEN_URL_TOOL_NAMES,
                ImageGenerationTool.NAME,
                MemoryTool.NAME,
                PostgresTool.NAME,
            }
        ):
            objects.append(
                packets.CustomToolDelta(
                    tool_name=self.call.name,
                    tool_id=self.tool_id,
                    response_type="text",
                    data=content,
                )
            )
            self._last_content = content
        self._last_details = details
        return [packets.Packet(placement=self.placement, obj=obj) for obj in objects]

    def _sandbox_packets(
        self,
        details: SandboxOutputDelta
        | SandboxExecResult
        | ApplyPatchResult
        | PublishedFiles,
    ) -> list[packets.Packet]:
        """Every output delta renders; a result renders once."""
        if isinstance(details, SandboxOutputDelta):
            obj: packets.PacketObj = packets.ExecOutputDelta(text=details.text)
        elif details == self._last_details:
            return []
        elif isinstance(details, ApplyPatchResult):
            self._last_details = details
            obj = packets.ApplyPatchEnd(files=details.files)
        elif isinstance(details, PublishedFiles):
            self._last_details = details
            obj = packets.PublishFilesEnd(
                files=[
                    PublishedFileView.model_validate(file.model_dump())
                    for file in details.files
                ]
            )
        else:
            self._last_details = details
            obj = packets.ExecEnd(
                output=details.output
                if details.spilled is None
                else _spilled_card_text(details.spilled),
                exit_code=details.exit_code,
                completion=details.completion,
                session_id=details.session_id,
                wall_time_seconds=details.wall_time_seconds,
                truncated=details.truncated,
            )
        return [packets.Packet(placement=self.placement, obj=obj)]

    def complete(self, result: ToolResultFields | None) -> list[packets.Packet]:
        """Render the result and end the call's section.

        The part of the result that an amendment added follows the section end,
        as it does when the amendment arrives live.
        """
        if self._finished:
            return []
        output = self.start()
        output.extend(self._result_packets(result))
        self._finished = True
        # A stopped call reports no more progress, so its open cards close here.
        output.extend(
            packets.Packet(
                placement=self.placement,
                obj=packets.ToolApprovalResolved(
                    approval_id=approval_id, outcome="cancelled"
                ),
            )
            for approval_id in self._open_command_approvals
        )
        self._open_command_approvals.clear()
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

    def _result_packets(self, result: ToolResultFields | None) -> list[packets.Packet]:
        """The packets of a final result of the call, before its section end."""
        end = self._own_end
        if (
            end is not None
            and result is not None
            and result.is_error
            and not isinstance(result.details, (SandboxExecResult, ApplyPatchResult))
        ):
            # A failed sandbox call has no process result, file changes or
            # published files.
            return [
                packets.Packet(placement=self.placement, obj=end(error=result.text))
            ]
        if result is None:
            return []
        if (
            self._generic_display
            and result.is_error
            and result.details is None
            and not self._not_approved
        ):
            # A rejected call (ToolCallException) has no public error details.
            # Its text goes to the model and can be private, so the card gets
            # only the failure. An error packet would end the widget's stream.
            return [
                packets.Packet(
                    placement=self.placement,
                    obj=packets.CustomToolDelta(
                        tool_name=self.call.name,
                        tool_id=self.tool_id,
                        response_type=CUSTOM_TOOL_ERROR_RESPONSE_TYPE,
                    ),
                )
            ]
        return self._detail_packets(
            result.details, "" if result.is_error else result.text
        )

    def amend(self, result: ToolResultFields) -> list[packets.Packet]:
        """Render the result that a release hook set for the call.

        An ended call renders only what the amendment added. Any other call
        completes with the result.
        """
        if not self._finished:
            return self.complete(result)
        return self._amendment_packets(result)

    def _amendment_packets(self, result: ToolResultFields) -> list[packets.Packet]:  # noqa: ARG002
        """What a release hook added to the result after the call ended.

        The generic display cannot tell an amendment apart from the result it
        replaces, so it adds nothing; the saved result shows on replay.
        """
        return []


class QuestionToolRenderer(ToolRenderer):
    """A question call shows only its card: its questions, then how they
    ended."""

    @override
    def consume(
        self,
        event: ToolStartEvent
        | ToolUpdateEvent
        | ToolEndEvent
        | InputRequiredEvent
        | InputEndedEvent,
    ) -> list[packets.Packet]:
        obj: packets.ToolQuestionRequest | packets.ToolQuestionResolved
        if isinstance(event, InputRequiredEvent):
            # The tool opened the request after it validated the arguments.
            obj = packets.ToolQuestionRequest(
                question_request_id=event.request.request_id,
                tool_call_id=self.call.id,
                questions=parse_tool_arguments(
                    QUESTION_SHAPES_BY_NAME[self.call.name].arguments,
                    tool_arguments_for_display(self.call),
                ).request(),
            )
        elif isinstance(event, InputEndedEvent):
            obj = question_resolved(event.request.request_id, event.answer)
        else:
            return super().consume(event)
        return [packets.Packet(placement=self.placement, obj=obj)]

    @override
    def start(self) -> list[packets.Packet]:
        self._started = True
        return []

    @override
    def update(
        self, details: BaseModel | None, content: str = ""
    ) -> list[packets.Packet]:
        return []

    @override
    def complete(self, result: ToolResultFields | None) -> list[packets.Packet]:
        if self._finished:
            return []
        self._finished = True
        return [packets.Packet(placement=self.placement, obj=packets.SectionEnd())]


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
    `CodeModeStart.cell_id` (a wait call) or on the final
    `CodeModeDelta.cell_id` (a run call). The cell's closing record follows the section end of its
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
        if self.call.name in WAIT_TOOL_NAMES:
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
        if call.state == "unfinished":
            # Stopped with its cell: no end packet, as a stopped top-level
            # call has none.
            return self._child(call).complete(None)
        return self._child(call).complete(call.as_result())

    def _complete_open_children(self) -> list[packets.Packet]:
        return [
            packet
            for index in sorted(self._children)
            for packet in self._children[index].complete(None)
        ]

    def _result_packets(self, result: ToolResultFields | None) -> list[packets.Packet]:
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
        stdout = (
            execution.stdout
            if execution.spilled is None
            else _spilled_card_text(execution.spilled)
        )
        replace = bool(self._stdout) and self._stdout != stdout
        output.append(
            packets.Packet(
                placement=self.placement,
                obj=packets.CodeModeDelta(
                    stdout=stdout if replace or not self._stdout else "",
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
    def _amendment_packets(self, result: ToolResultFields) -> list[packets.Packet]:
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
    """The renderer of a tool call: a code mode card, a question card, or the
    generic tool display."""
    renderer = (
        CodeModeRenderer
        if call.name in CODE_MODE_TOOL_NAMES
        else QuestionToolRenderer
        if call.name in QUESTION_TOOL_NAMES
        else ToolRenderer
    )
    return renderer(call, placement, tool_id, display_name)
