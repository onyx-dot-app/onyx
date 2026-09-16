"""Convert tool output into the frontend's tool-specific packet types.

Live updates pass through project_tool_progress. tool_display_progress reconstructs
updates from recorded arguments and results for history and completion. ToolProgressTracker
removes fields already streamed before completion emits the reconstructed updates.
"""

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from onyx.agents.tools import ToolProgress
from onyx.coding_agent.tool_definitions import (
    CODING_AGENT_TOOL_NAME,
    GENERATE_ANSWER_TOOL_NAME,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TASK_KEY,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.models import ToolCall, ToolResult
from onyx.server.query_and_chat.streaming_models import (
    BashToolDelta,
    BashToolStart,
    CodingAgentFinal,
    CodingAgentStart,
    CustomToolArgs,
    CustomToolDelta,
    CustomToolStart,
    FileReaderResult,
    FileReaderStart,
    ImageGenerationFinal,
    ImageGenerationToolHeartbeat,
    ImageGenerationToolStart,
    MemoryToolDelta,
    MemoryToolStart,
    OpenUrlDocuments,
    OpenUrlStart,
    OpenUrlUrls,
    PacketObj,
    PythonToolDelta,
    PythonToolStart,
    ResearchAgentStart,
    SearchToolDocumentsDelta,
    SearchToolFilterDelta,
    SearchToolQueriesDelta,
    SearchToolStart,
)
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    LlmPythonExecutionResult,
)
from onyx.tools.progress import (
    BashOutput,
    BashStarted,
    CodingCompleted,
    CodingStarted,
    CustomToolArguments,
    CustomToolOutput,
    CustomToolStarted,
    FileReadResult,
    FileReadStarted,
    ImageGenerationHeartbeat,
    ImageGenerationStarted,
    ImagesGenerated,
    MemoryStarted,
    MemoryUpdated,
    OpenUrlStarted,
    OpenUrlTargets,
    PythonOutput,
    PythonStarted,
    ResearchStarted,
    SearchDocuments,
    SearchFilters,
    SearchQueries,
    SearchStarted,
    UrlDocuments,
)
from onyx.tools.tool_implementations.bash.bash_tool import (
    BashArguments,
    BashTool,
    LlmBashExecutionResult,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentArguments,
)
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import (
    PythonArguments,
    PythonTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

_STRING_LIST = TypeAdapter(list[str])
_TEXT = TypeAdapter(str)
_JSON_VALUE = TypeAdapter(JsonValue)

_PROGRESS_PACKETS: dict[type[BaseModel], type[PacketObj]] = {
    SearchStarted: SearchToolStart,
    ResearchStarted: ResearchAgentStart,
    SearchQueries: SearchToolQueriesDelta,
    SearchFilters: SearchToolFilterDelta,
    SearchDocuments: SearchToolDocumentsDelta,
    OpenUrlStarted: OpenUrlStart,
    OpenUrlTargets: OpenUrlUrls,
    UrlDocuments: OpenUrlDocuments,
    ImageGenerationStarted: ImageGenerationToolStart,
    ImageGenerationHeartbeat: ImageGenerationToolHeartbeat,
    ImagesGenerated: ImageGenerationFinal,
    PythonStarted: PythonToolStart,
    PythonOutput: PythonToolDelta,
    CustomToolStarted: CustomToolStart,
    CustomToolArguments: CustomToolArgs,
    CustomToolOutput: CustomToolDelta,
    FileReadStarted: FileReaderStart,
    FileReadResult: FileReaderResult,
    MemoryStarted: MemoryToolStart,
    MemoryUpdated: MemoryToolDelta,
    CodingStarted: CodingAgentStart,
    CodingCompleted: CodingAgentFinal,
    BashStarted: BashToolStart,
    BashOutput: BashToolDelta,
}


def project_tool_progress(progress: ToolProgress) -> PacketObj | None:
    """Encode a typed tool update as a frontend packet body."""
    if progress.details is None:
        return None
    packet_type = _PROGRESS_PACKETS.get(type(progress.details))
    if packet_type is None:
        raise ValueError(
            f"Unsupported tool progress: {type(progress.details).__name__}"
        )
    return packet_type.model_validate(progress.details.model_dump())


def tool_display_progress(
    call: ToolCall, result: ToolResult | None, *, tool_id: int | None = None
) -> list[ToolProgress]:
    """Reconstruct display updates from a tool call and its available result.

    Used for history replay and to fill gaps when a tool finishes without streaming
    every display field. Incomplete arguments are allowed while a result is pending.
    """
    if call.name in {
        THINK_TOOL_NAME,
        GENERATE_PLAN_TOOL_NAME,
        GENERATE_REPORT_TOOL_NAME,
        GENERATE_ANSWER_TOOL_NAME,
    }:
        return []
    try:
        return _tool_display_progress(call, result, tool_id=tool_id)
    except ValidationError:
        if result is not None:
            raise
        logger.debug("Incomplete tool arguments cannot be displayed: %s", call.name)
        return []


def _tool_display_progress(
    call: ToolCall, result: ToolResult | None, *, tool_id: int | None
) -> list[ToolProgress]:
    details = result.details if result is not None else None
    if result is not None and result.is_error and details is None:
        return []
    updates: list[BaseModel]
    if call.name in {SearchTool.NAME, WebSearchTool.NAME}:
        updates = [
            SearchStarted(is_internet_search=call.name == WebSearchTool.NAME),
            SearchQueries(
                queries=_STRING_LIST.validate_python(call.arguments.get("queries", []))
            ),
        ]
        if isinstance(details, SearchDocsResponse):
            updates.append(
                SearchDocuments(documents=details.displayed_docs or details.search_docs)
            )
    elif call.name == OpenURLTool.NAME:
        updates = [
            OpenUrlStarted(),
            OpenUrlTargets(
                urls=_STRING_LIST.validate_python(call.arguments.get("urls", []))
            ),
        ]
        if isinstance(details, SearchDocsResponse):
            updates.append(
                UrlDocuments(documents=details.displayed_docs or details.search_docs)
            )
    elif call.name == ImageGenerationTool.NAME:
        updates = [ImageGenerationStarted()]
        if isinstance(details, FinalImageGenerationResponse):
            updates.append(ImagesGenerated(images=details.generated_images))
    elif call.name == FileReaderTool.NAME:
        updates = [FileReadStarted()]
        if isinstance(details, FileReadResult):
            updates.append(details)
    elif call.name == MemoryTool.NAME:
        updates = [MemoryStarted()]
        if isinstance(details, MemoryUpdated):
            updates.append(details)
    elif call.name == PythonTool.NAME:
        args = PythonArguments.model_validate(call.arguments)
        updates = [PythonStarted(code=args.code)]
        if result is not None:
            updates.append(_python_output(result))
    elif call.name == BashTool.NAME:
        args = BashArguments.model_validate(call.arguments)
        updates = [BashStarted(cmd=args.cmd)]
        if result is not None:
            updates.append(_bash_output(result))
    elif call.name == CODING_AGENT_TOOL_NAME:
        args = CodingAgentArguments.model_validate(call.arguments)
        updates = [CodingStarted(query=args.query, repo=args.github_repo)]
        if result is not None and not result.is_error:
            updates.append(CodingCompleted(answer=result.text))
    elif call.name == RESEARCH_AGENT_TOOL_NAME:
        updates = [
            ResearchStarted(
                research_task=_TEXT.validate_python(
                    call.arguments.get(RESEARCH_AGENT_TASK_KEY, "")
                )
            )
        ]
    else:
        updates = _custom_updates(call, result, tool_id)
    return [ToolProgress(details=update) for update in updates]


def _custom_updates(
    call: ToolCall, result: ToolResult | None, tool_id: int | None
) -> list[BaseModel]:
    updates: list[BaseModel] = [
        CustomToolStarted(tool_name=call.name, tool_id=tool_id),
        CustomToolArguments(
            tool_name=call.name,
            tool_args={
                key: value
                for key, value in call.arguments.items()
                if key != "requestBody"
            },
        ),
    ]
    if result is not None:
        updates.append(_custom_output(call, result, tool_id))
    return updates


def _custom_output(
    call: ToolCall, result: ToolResult, tool_id: int | None
) -> CustomToolOutput:
    details = result.details
    if not isinstance(details, CustomToolCallSummary):
        return CustomToolOutput(
            tool_name=call.name, tool_id=tool_id, response_type="text", data=result.text
        )
    files = details.tool_result
    return CustomToolOutput(
        tool_name=details.tool_name,
        tool_id=tool_id,
        response_type=details.response_type,
        data=None
        if isinstance(files, CustomToolUserFileSnapshot)
        else _JSON_VALUE.validate_python(files),
        file_ids=files.file_ids
        if isinstance(files, CustomToolUserFileSnapshot)
        else None,
        error=details.error,
    )


def _python_output(result: ToolResult) -> PythonOutput:
    if result.is_error:
        return PythonOutput(stderr=result.text)
    output = LlmPythonExecutionResult.model_validate_json(result.text)
    return PythonOutput(
        stdout=output.stdout,
        stderr=output.stderr,
        file_ids=[file.file_link.rsplit("/", 1)[-1] for file in output.generated_files],
    )


def _bash_output(result: ToolResult) -> BashOutput:
    if result.is_error:
        return BashOutput(stderr=result.text)
    output = LlmBashExecutionResult.model_validate_json(result.text)
    return BashOutput(
        stdout=output.stdout,
        stderr=output.stderr,
        exit_code=output.exit_code,
        timed_out=output.timed_out,
    )


class ToolProgressTracker:
    """Remove streamed fields from reconstructed completion updates for one tool call.

    Python output needs text lengths and file IDs tracked separately;
    other update types are emitted once per call.
    """

    def __init__(self) -> None:
        self._kinds: set[type[BaseModel]] = set()
        self._stdout_length = 0
        self._stderr_length = 0
        self._file_ids: set[str] = set()

    def observe(self, progress: ToolProgress) -> None:
        details = progress.details
        if details is None:
            return
        self._kinds.add(type(details))
        if isinstance(details, PythonOutput):
            self._stdout_length += len(details.stdout)
            self._stderr_length += len(details.stderr)
            self._file_ids.update(details.file_ids)

    def remaining(self, progress: ToolProgress) -> ToolProgress | None:
        details = progress.details
        if isinstance(details, PythonOutput):
            delta = PythonOutput(
                stdout=details.stdout[self._stdout_length :],
                stderr=details.stderr[self._stderr_length :],
                file_ids=[
                    file_id
                    for file_id in details.file_ids
                    if file_id not in self._file_ids
                ],
            )
            return (
                ToolProgress(details=delta)
                if delta.stdout or delta.stderr or delta.file_ids
                else None
            )
        if details is None or type(details) in self._kinds:
            return None
        return progress
