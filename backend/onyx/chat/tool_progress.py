from pydantic import BaseModel

from onyx.agents.tools import ToolProgress
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
    if progress.details is None:
        return None
    packet_type = _PROGRESS_PACKETS.get(type(progress.details))
    if packet_type is None:
        raise ValueError(
            f"Unsupported tool progress: {type(progress.details).__name__}"
        )
    return packet_type.model_validate(progress.details.model_dump())
