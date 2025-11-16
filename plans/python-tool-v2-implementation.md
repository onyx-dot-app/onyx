# Python Tool (V2) - Implementation Plan

## Issues to Address

Add a new built-in Python code execution tool using the v2 tool implementation pattern (`@function_tool` decorator) that:
- Executes arbitrary Python code through the Code Interpreter service
- Supports file upload/download workflows
- Integrates seamlessly with the existing v2 tool architecture
- Provides streaming progress updates to the frontend
- Handles execution errors, timeouts, and workspace file management

## Critical Implementation Notes

### Known Issues Fixed

1. **Tool Constructor Integration (CRITICAL)**: The Python tool must be explicitly handled in `backend/onyx/tools/tool_constructor.py` with an elif clause that instantiates `PythonTool`. Without this, the tool passes availability checks but is never added to the tools list, causing "No tools found for forced tool IDs: [X]" errors when configured in an assistant.

2. **V2 Tool Registration (CRITICAL)**: The Python tool must be added to `BUILT_IN_TOOL_MAP_V2` in `backend/onyx/tools/built_in_tools_v2.py`. This map is used by `adapter_v1_to_v2.py` to convert Tool instances to FunctionTool instances that the v2 agent framework can execute. Without this, the v2 agent cannot discover or execute the Python tool's `@function_tool` decorated function.

3. **Built-in Tools Registration**: Python tool must be added to both `BUILT_IN_TOOL_TYPES` union and `BUILT_IN_TOOL_MAP` in `backend/onyx/tools/built_in_tools.py`. This enables tool discovery and availability checking.

4. **Default Assistant Page Integration**: The Python tool must be added to:
   - Backend: `ORDERED_TOOL_IDS` in `backend/onyx/server/features/default_assistant/api.py`
   - Frontend: Tool availability tooltip in `web/src/app/admin/configuration/default-assistant/page.tsx`
   - Frontend: Tool constants in `web/src/app/chat/components/tools/constants.ts`

## Important Notes

### V2 Tool Architecture

From examining existing v2 tools (`backend/onyx/tools/tool_implementations_v2/`):

**V2 Tool Pattern:**
- Use `@function_tool` decorator from the `agents` library for the main tool function
- Use `@tool_accounting` decorator for the core implementation function
- Accept `RunContextWrapper[ChatTurnContext]` as the first parameter
- Return JSON-serialized results using `TypeAdapter`
- Emit streaming `Packet` objects for frontend updates
- Update `run_context.context` with iteration instructions and answers

**Key Components:**
- **Core Function:** Contains actual implementation logic with `@tool_accounting`
- **Tool Function:** Wrapper with `@function_tool` that calls core and serializes results
- **Result Models:** Pydantic models in `tool_result_models.py` for structured responses
- **Streaming Models:** Packet types in `streaming_models.py` for real-time updates

**Existing V2 Tools:**
1. `web_search` (`web.py`) - Internet search with result streaming
2. `open_url` (`web.py`) - Fetch web page content
3. `internal_search` (`internal_search.py`) - Search internal knowledge base
4. `image_generation` (`image_generation.py`) - Generate images with file handling

### Code Interpreter Service

**API Endpoints:**
- `POST /v1/execute` - Execute Python code synchronously
- `POST /v1/files` - Upload files for code execution
- `GET /v1/files` - List uploaded files
- `GET /v1/files/{file_id}` - Download file
- `DELETE /v1/files/{file_id}` - Delete file

**ExecuteRequest Schema:**
```python
{
  "code": str,              # Python source to execute
  "stdin": str | None,      # Optional stdin
  "timeout_ms": int,        # Execution timeout (default: 2000)
  "files": [                # Optional files to stage
    {
      "path": str,          # Relative path in workspace
      "file_id": str        # UUID of uploaded file
    }
  ]
}
```

**ExecuteResponse Schema:**
```python
{
  "stdout": str,
  "stderr": str,
  "exit_code": int | None,
  "timed_out": bool,
  "duration_ms": int,
  "files": [                # Workspace snapshot after execution
    {
      "path": str,
      "kind": "file" | "directory",
      "file_id": str | None  # Only for files
    }
  ]
}
```

**Key Constraints:**
- No internet access in execution environment
- Available libraries: numpy, pandas, scipy, matplotlib, PIL, etc.
- Execution happens in isolated Docker container
- Files are staged before execution and captured after

### File Store Integration

From `backend/onyx/file_store/utils.py` and `backend/onyx/file_store/file_store.py`:

**Existing Utilities:**
- `file_store.save_file(content, display_name, file_origin, file_type)` - Save files directly with MIME type
- `build_frontend_file_url(file_id)` - Generate URL for frontend
- `get_default_file_store().read_file(file_id)` - Read file contents
- `InMemoryChatFile` - Model for chat-associated files

**File Handling Pattern (Updated for Python Tool):**
1. Tool downloads file content from Code Interpreter
2. Detect MIME type using `mimetypes.guess_type(filename)`
3. Call `file_store.save_file()` directly with proper MIME type and FileOrigin.CHAT_UPLOAD
4. Store file_ids in `IterationAnswer`
5. Return file references to LLM
6. Frontend can download/display files

**Note:** The `save_files()` utility is NOT used because it only supports image formats (PNG, JPEG, GIF, WEBP). Python tool generates various file types (CSV, TXT, JSON, etc.), so we use `file_store.save_file()` directly with automatic MIME type detection.

### Configuration & Environment

From `backend/onyx/configs/app_configs.py`:
- Environment variables for service URLs follow pattern: `{SERVICE}_BASE_URL`
- Timeout configs follow pattern: `{SERVICE}_TIMEOUT`
- Add: `CODE_INTERPRETER_BASE_URL` and `CODE_INTERPRETER_DEFAULT_TIMEOUT_MS`

### Tool Architecture Pattern

The Python tool uses a **dual architecture**:

1. **`PythonTool` class** (`backend/onyx/tools/tool_implementations/python/python_tool.py`):
   - Extends `Tool` base class for infrastructure integration
   - Provides `is_available()` method to check if Code Interpreter service URL is configured
   - Registered in `BUILT_IN_TOOL_MAP` for tool discovery
   - Stub implementations throw errors - this tool is only meant for v2 agent framework

2. **`python` function** (`backend/onyx/tools/tool_implementations_v2/python.py`):
   - Decorated with `@function_tool` for v2 agent framework
   - Contains actual execution logic
   - Handles file staging, code execution, output truncation, and file generation
   - Returns JSON-serialized results to LLM

This pattern follows the same approach as `WebSearchTool`:
- The class provides availability checking and tool metadata
- The v2 function handles actual execution
- Legacy Tool methods raise errors since they're not used

**How they work together:**
- Tool constructor checks `PythonTool.is_available()` to determine if tool should be instantiated
- If available, tool appears in persona/assistant configuration
- When agent framework runs, it discovers the `@function_tool` decorated `python_execution` function
- Actual execution flows through the v2 function, not the `PythonTool.run()` method

## Implementation Strategy

### 0. Chat File Access Infrastructure (PREREQUISITE)

**Problem:** The `ChatTurnContext` model does not have a `chat_files` field by default, so v2 tools cannot access files uploaded by users in the chat.

**Solution:** Add `chat_files` field to `ChatTurnContext` and thread files through the execution call chain.

**Update ChatTurnContext Model** (`backend/onyx/chat/turn/models.py`):
```python
from onyx.file_store.models import InMemoryChatFile

@dataclass
class ChatTurnContext:
    """Context class to hold search tool and other dependencies"""

    chat_session_id: UUID
    message_id: int
    research_type: ResearchType
    run_dependencies: ChatTurnDependencies
    current_run_step: int = 0
    iteration_instructions: list[IterationInstructions] = dataclasses.field(default_factory=list)
    global_iteration_responses: list[IterationAnswer] = dataclasses.field(default_factory=list)
    should_cite_documents: bool = False
    documents_processed_by_citation_context_handler: int = 0
    tool_calls_processed_by_citation_context_handler: int = 0
    fetched_documents_cache: dict[str, FetchedDocumentCacheEntry] = dataclasses.field(default_factory=dict)
    citations: list[CitationInfo] = dataclasses.field(default_factory=list)
    current_output_index: int | None = None

    # ADD THIS FIELD:
    chat_files: list[InMemoryChatFile] = dataclasses.field(default_factory=list)
```

**Update fast_chat_turn signature** (`backend/onyx/chat/turn/fast_chat_turn.py`):
```python
@unified_event_stream
def fast_chat_turn(
    messages: list[AgentSDKMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
    latest_query_files: list[InMemoryChatFile] | None = None,  # ADD THIS PARAMETER
) -> None:
    """Main fast chat turn function that calls the core logic with default parameters."""
    _fast_chat_turn_core(
        messages,
        dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
        force_use_tool=force_use_tool,
        latest_query_files=latest_query_files,  # PASS IT THROUGH
    )
```

**Update _fast_chat_turn_core** (`backend/onyx/chat/turn/fast_chat_turn.py`):
```python
def _fast_chat_turn_core(
    messages: list[AgentSDKMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
    starter_context: ChatTurnContext | None = None,
    latest_query_files: list[InMemoryChatFile] | None = None,  # ADD THIS PARAMETER
) -> None:
    reset_cancel_status(chat_session_id, dependencies.redis_client)

    ctx = starter_context or ChatTurnContext(
        run_dependencies=dependencies,
        chat_session_id=chat_session_id,
        message_id=message_id,
        research_type=research_type,
        chat_files=latest_query_files or [],  # ADD THIS TO CONTEXT CREATION
    )
    # ... rest of function
```

**Pass files from process_message** (`backend/onyx/chat/process_message.py` in `_fast_message_stream` function):
```python
# Around line 802 where fast_chat_turn.fast_chat_turn is called
return fast_chat_turn.fast_chat_turn(
    messages=messages,
    dependencies=ChatTurnDependencies(
        llm_model=llm_model,
        model_settings=model_settings,
        llm=answer.graph_tooling.primary_llm,
        tools=tools,
        db_session=db_session,
        redis_client=redis_client,
        emitter=emitter,
        user_or_none=user_or_none,
        prompt_config=prompt_config,
    ),
    chat_session_id=chat_session_id,
    message_id=reserved_message_id,
    research_type=answer.graph_config.behavior.research_type,
    prompt_config=prompt_config,
    force_use_tool=answer.graph_tooling.force_use_tool,
    latest_query_files=answer.graph_inputs.files,  # ADD THIS LINE
)
```

**File Structure:** Files are `InMemoryChatFile` objects with:
- `file_id`: str - Unique identifier
- `content`: bytes - File content already loaded in memory
- `file_type`: ChatFileType - IMAGE, DOC, PLAIN_TEXT, CSV, USER_KNOWLEDGE
- `filename`: str | None - Original filename

**Access Pattern in Python Tool:**
```python
# After these changes, access files in the tool like this:
chat_files = run_context.context.chat_files

for chat_file in chat_files:
    file_content = chat_file.content  # bytes already in memory
    filename = chat_file.filename
    file_type = chat_file.file_type
```

### 1. Configuration & Service Client

**Add Environment Variables** (`backend/onyx/configs/app_configs.py`):
```python
CODE_INTERPRETER_BASE_URL = os.environ.get(
    "CODE_INTERPRETER_BASE_URL"
)

CODE_INTERPRETER_DEFAULT_TIMEOUT_MS = int(
    os.environ.get("CODE_INTERPRETER_DEFAULT_TIMEOUT_MS", "30000")
)

CODE_INTERPRETER_MAX_OUTPUT_LENGTH = int(
    os.environ.get("CODE_INTERPRETER_MAX_OUTPUT_LENGTH", "50000")
)
```

**Create Service Client** (`backend/onyx/tools/tool_implementations_v2/code_interpreter_client.py`):
```python
import base64
import requests
from typing import BinaryIO

from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL
from onyx.utils.logger import setup_logger

logger = setup_logger()


class WorkspaceFile(BaseModel):
    """File in execution workspace"""
    path: str
    kind: Literal["file", "directory"]
    file_id: str | None = None


class ExecuteResponse(BaseModel):
    """Response from code execution"""
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    files: list[WorkspaceFile]


class CodeInterpreterClient:
    """Client for Code Interpreter service"""

    def __init__(self, base_url: str = CODE_INTERPRETER_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def execute(
        self,
        code: str,
        stdin: str | None = None,
        timeout_ms: int = 30000,
        files: list[dict[str, str]] | None = None,
    ) -> ExecuteResponse:
        """Execute Python code"""
        url = f"{self.base_url}/v1/execute"

        payload = {
            "code": code,
            "timeout_ms": timeout_ms,
        }

        if stdin is not None:
            payload["stdin"] = stdin

        if files:
            payload["files"] = files

        response = requests.post(url, json=payload, timeout=timeout_ms / 1000 + 10)
        response.raise_for_status()

        return ExecuteResponse(**response.json())

    def upload_file(self, file_content: bytes, filename: str) -> str:
        """Upload file to Code Interpreter and return file_id"""
        url = f"{self.base_url}/v1/files"

        files = {"file": (filename, file_content)}
        response = requests.post(url, files=files, timeout=30)
        response.raise_for_status()

        return response.json()["file_id"]

    def download_file(self, file_id: str) -> bytes:
        """Download file from Code Interpreter"""
        url = f"{self.base_url}/v1/files/{file_id}"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        return response.content

    def delete_file(self, file_id: str) -> None:
        """Delete file from Code Interpreter"""
        url = f"{self.base_url}/v1/files/{file_id}"

        response = requests.delete(url, timeout=10)
        response.raise_for_status()
```

### 2. Streaming Models

**Add to** `backend/onyx/server/query_and_chat/streaming_models.py`:
```python
class PythonToolStart(BaseObj):
    type: Literal["python_tool_start"] = "python_tool_start"


class PythonToolDelta(BaseObj):
    type: Literal["python_tool_delta"] = "python_tool_delta"

    stdout: str = ""
    stderr: str = ""
    file_ids: list[str] = []  # IDs of generated files
```

**Note:** We don't need a separate `PythonToolFile` model in streaming. The lightweight `file_ids` list follows the pattern used by `CustomToolDelta`. Full file metadata (filename, path, url) is already captured in `PythonExecutionFile` within the `LlmPythonExecutionResult` and `IterationAnswer`.

**Frontend TypeScript Types** (`web/src/app/chat/services/streamingModels.ts`):
```typescript
export interface PythonToolStart extends BaseObj {
  type: "python_tool_start";
}

export interface PythonToolDelta extends BaseObj {
  type: "python_tool_delta";
  stdout: string;
  stderr: string;
  file_ids: string[];
}

// Add to PacketType enum:
// PYTHON_TOOL_START = "python_tool_start",
// PYTHON_TOOL_DELTA = "python_tool_delta",
```

### 3. Tool Result Models

**Add to** `backend/onyx/tools/tool_implementations_v2/tool_result_models.py`:
```python
class PythonExecutionFile(BaseModel):
    """File generated during Python execution"""
    file_id: str
    filename: str
    path: str
    url: str


class LlmPythonExecutionResult(BaseModel):
    """Result from Python code execution"""
    type: Literal["python_execution"] = "python_execution"

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    generated_files: list[PythonExecutionFile]
    error: str | None = None
```

### 4. Tool Wrapper Class (for availability checking)

**Create** `backend/onyx/tools/tool_implementations/python/python_tool.py`:
```python
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()

_GENERIC_ERROR_MESSAGE = "PythonTool should only be used by the Deep Research Agent with v2 tools, not via direct tool calling."


class PythonTool(Tool[None]):
    """
    Wrapper class for Python code execution tool.

    This class provides availability checking and integrates with the Tool infrastructure.
    Actual execution is handled by the v2 function-based implementation.
    """
    _NAME = "run_python"
    _DESCRIPTION = "Execute Python code in a secure, isolated environment. Never call this tool directly."
    _DISPLAY_NAME = "Python Execution"

    def __init__(self, tool_id: int) -> None:
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

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """
        Available if Code Interpreter service URL is configured.

        Only checks if CODE_INTERPRETER_BASE_URL is set - does not perform health check.
        Service failures will be handled gracefully at execution time.
        """
        from onyx.configs.app_configs import CODE_INTERPRETER_BASE_URL

        if not CODE_INTERPRETER_BASE_URL:
            logger.debug("Python tool unavailable: CODE_INTERPRETER_BASE_URL not configured")
            return False

        return True

    def tool_definition(self) -> dict:
        """Tool definition for LLMs that support explicit tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python source code to execute",
                        },
                    },
                    "required": ["code"],
                },
            },
        }

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def run(
        self, override_kwargs: None = None, **llm_kwargs: str
    ) -> Generator[ToolResponse, None, None]:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        """Not supported - Python tool is only used via v2 agent framework."""
        raise ValueError(_GENERIC_ERROR_MESSAGE)
```

**Note:** This class follows the same pattern as `WebSearchTool` - it provides the `Tool` interface for availability checking and tool registration, but actual execution happens in the v2 implementation. The `is_available()` method only checks if the service URL is configured; service failures are handled gracefully at execution time. The old Tool methods raise errors because this tool is only meant to be used via the v2 agent framework.

**Update** `backend/onyx/tools/built_in_tools.py`:
```python
from onyx.tools.tool_implementations.python.python_tool import PythonTool

# Add to BUILT_IN_TOOL_TYPES union
BUILT_IN_TOOL_TYPES = Union[
    SearchTool, ImageGenerationTool, WebSearchTool, KnowledgeGraphTool, PythonTool
]

# Add to BUILT_IN_TOOL_MAP
BUILT_IN_TOOL_MAP: dict[str, Type[BUILT_IN_TOOL_TYPES]] = {
    SearchTool.__name__: SearchTool,
    ImageGenerationTool.__name__: ImageGenerationTool,
    WebSearchTool.__name__: WebSearchTool,
    KnowledgeGraphTool.__name__: KnowledgeGraphTool,
    PythonTool.__name__: PythonTool,
}
```

**Update** `backend/onyx/tools/built_in_tools_v2.py`:
```python
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations_v2 import python_execution

# Add to BUILT_IN_TOOL_MAP_V2
BUILT_IN_TOOL_MAP_V2: dict[str, list[FunctionTool]] = {
    SearchTool.__name__: [internal_search],
    ImageGenerationTool.__name__: [image_generation],
    WebSearchTool.__name__: [web_search, open_url],
    PythonTool.__name__: [python_execution],  # Add this line
}
```

**Note:** `BUILT_IN_TOOL_MAP_V2` is critical for the v2 agent framework. It maps Tool wrapper class names to their v2 `@function_tool` decorated implementations. The `adapter_v1_to_v2.py` module uses this map in `tools_to_function_tools()` to convert Tool instances (v1 style) into FunctionTool instances (v2 style) that the agent framework can execute.

**Update** `backend/onyx/tools/tool_constructor.py` to instantiate PythonTool:
```python
# After the KnowledgeGraphTool elif clause (around line 312):

            # Handle Python Tool
            elif tool_cls.__name__ == "PythonTool":
                from onyx.tools.tool_implementations.python.python_tool import (
                    PythonTool,
                )

                tool_dict[db_tool_model.id] = [PythonTool(tool_id=db_tool_model.id)]
```

**Note:** This is critical - without this, the Python tool passes availability checks but never gets instantiated into the tools list, causing "No tools found for forced tool IDs" errors when the tool is configured in an assistant.

### 5. Core V2 Tool Implementation

**Create** `backend/onyx/tools/tool_implementations_v2/python_execution.py`:
```python
from typing import cast

from agents import function_tool, RunContextWrapper
from pydantic import TypeAdapter

from onyx.agents.agent_search.dr.models import IterationAnswer, IterationInstructions
from onyx.chat.turn.models import ChatTurnContext
from onyx.file_store.utils import save_files, build_frontend_file_url, get_default_file_store
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    PythonToolStart,
    PythonToolDelta,
)
from onyx.tools.tool_implementations_v2.code_interpreter_client import (
    CodeInterpreterClient,
    ExecuteResponse,
)
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmPythonExecutionResult,
    PythonExecutionFile,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


@tool_accounting
def _python_execution_core(
    run_context: RunContextWrapper[ChatTurnContext],
    code: str,
    client: CodeInterpreterClient,
) -> LlmPythonExecutionResult:
    """Core Python execution logic"""
    from onyx.configs.app_configs import (
        CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
        CODE_INTERPRETER_MAX_OUTPUT_LENGTH,
    )

    index = run_context.context.current_run_step
    emitter = run_context.context.run_dependencies.emitter

    # Emit start event
    emitter.emit(
        Packet(
            ind=index,
            obj=PythonToolStart(),
        )
    )

    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="Executing Python code",
            purpose="Running Python code",
            reasoning="Executing provided Python code in secure environment",
        )
    )

    # Get all files from chat context and upload to Code Interpreter
    files_to_stage = []

    # Access chat files directly from context (available after Step 0 changes)
    chat_files = run_context.context.chat_files

    for chat_file in chat_files:
        try:
            # Use file content already loaded in memory
            file_content = chat_file.content

            # Upload to Code Interpreter
            ci_file_id = client.upload_file(file_content, chat_file.filename)

            # Stage for execution
            files_to_stage.append({
                "path": chat_file.filename,
                "file_id": ci_file_id
            })

            logger.info(f"Staged file for Python execution: {chat_file.filename}")

        except Exception as e:
            logger.warning(f"Failed to stage file {chat_file.filename}: {e}")

    try:
        # Execute code with fixed timeout
        response: ExecuteResponse = client.execute(
            code=code,
            timeout_ms=CODE_INTERPRETER_DEFAULT_TIMEOUT_MS,
            files=files_to_stage if files_to_stage else None,
        )

        # Truncate output for LLM consumption
        truncated_stdout = response.stdout[:CODE_INTERPRETER_MAX_OUTPUT_LENGTH]
        truncated_stderr = response.stderr[:CODE_INTERPRETER_MAX_OUTPUT_LENGTH]

        stdout_truncated = len(response.stdout) > CODE_INTERPRETER_MAX_OUTPUT_LENGTH
        stderr_truncated = len(response.stderr) > CODE_INTERPRETER_MAX_OUTPUT_LENGTH

        if stdout_truncated:
            truncated_stdout += f"\n... [output truncated, {len(response.stdout) - CODE_INTERPRETER_MAX_OUTPUT_LENGTH} characters omitted]"

        if stderr_truncated:
            truncated_stderr += f"\n... [output truncated, {len(response.stderr) - CODE_INTERPRETER_MAX_OUTPUT_LENGTH} characters omitted]"

        # Handle generated files
        generated_files = []
        file_ids_to_cleanup = []

        for workspace_file in response.files:
            if workspace_file.kind == "file" and workspace_file.file_id:
                try:
                    # Download file from Code Interpreter
                    file_content = client.download_file(workspace_file.file_id)

                    # Save to Onyx file store
                    saved_file_ids = save_files(urls=[], base64_files=[
                        base64.b64encode(file_content).decode()
                    ])

                    if saved_file_ids:
                        onyx_file_id = saved_file_ids[0]
                        filename = workspace_file.path.split("/")[-1]

                        generated_files.append(
                            PythonExecutionFile(
                                file_id=onyx_file_id,
                                filename=filename,
                                path=workspace_file.path,
                                url=build_frontend_file_url(onyx_file_id),
                            )
                        )

                    # Mark for cleanup
                    file_ids_to_cleanup.append(workspace_file.file_id)

                except Exception as e:
                    logger.error(f"Failed to handle generated file {workspace_file.path}: {e}")

        # Cleanup Code Interpreter files (both generated and staged input files)
        for ci_file_id in file_ids_to_cleanup:
            try:
                client.delete_file(ci_file_id)
            except Exception as e:
                logger.warning(f"Failed to delete Code Interpreter generated file {ci_file_id}: {e}")

        # Cleanup staged input files
        for file_mapping in files_to_stage:
            try:
                client.delete_file(file_mapping["file_id"])
            except Exception as e:
                logger.warning(f"Failed to delete Code Interpreter staged file {file_mapping['file_id']}: {e}")

        # Emit delta with stdout/stderr and generated files
        emitter.emit(
            Packet(
                ind=index,
                obj=PythonToolDelta(
                    type="python_tool_delta",
                    stdout=truncated_stdout,
                    stderr=truncated_stderr,
                    file_ids=[f.file_id for f in generated_files],
                ),
            )
        )

        # Build result with truncated output
        result = LlmPythonExecutionResult(
            stdout=truncated_stdout,
            stderr=truncated_stderr,
            exit_code=response.exit_code,
            timed_out=response.timed_out,
            duration_ms=response.duration_ms,
            generated_files=generated_files,
            error=None if response.exit_code == 0 else truncated_stderr,
        )

        # Get tool ID from database
        from onyx.db.tools import get_tool_by_name
        from onyx.tools.tool_implementations.python.python_tool import PythonTool

        tool_id = get_tool_by_name(
            PythonTool.__name__, run_context.context.run_dependencies.db_session
        ).id

        # Store in iteration answer
        run_context.context.global_iteration_responses.append(
            IterationAnswer(
                tool=PythonTool.__name__,
                tool_id=tool_id,
                iteration_nr=index,
                parallelization_nr=0,
                question="Execute Python code",
                reasoning="Executing Python code in secure environment",
                answer=truncated_stdout if response.exit_code == 0 else truncated_stderr,
                cited_documents={},
                file_ids=[f.file_id for f in generated_files] if generated_files else None,
            )
        )

        return result

    except Exception as e:
        logger.error(f"Python execution failed: {e}")
        error_msg = str(e)

        # Emit error delta
        emitter.emit(
            Packet(
                ind=index,
                obj=PythonToolDelta(
                    type="python_tool_delta",
                    stdout="",
                    stderr=error_msg,
                    file_ids=[],
                ),
            )
        )

        # Return error result
        return LlmPythonExecutionResult(
            stdout="",
            stderr=error_msg,
            exit_code=-1,
            timed_out=False,
            duration_ms=0,
            generated_files=[],
            error=error_msg,
        )


@function_tool
def python_execution(
    run_context: RunContextWrapper[ChatTurnContext],
    code: str,
) -> str:
    """
    Execute Python code in a secure, isolated environment.

    This tool runs Python code with access to libraries like numpy, pandas, scipy,
    matplotlib, and PIL. The code executes in a sandboxed Docker container without
    internet access.

    Any files uploaded to the chat will be automatically available in the execution
    environment. Files generated by the code (plots, CSVs, etc.) will be captured
    and returned.

    Args:
        code: Python source code to execute

    Returns:
        JSON string containing stdout, stderr, exit code, execution time, and any generated files
    """
    # Create client
    client = CodeInterpreterClient()

    # Execute
    result = _python_execution_core(run_context, code, client)

    # Serialize and return
    adapter = TypeAdapter(LlmPythonExecutionResult)
    return adapter.dump_json(result).decode()


# Long description for tool documentation
PYTHON_EXECUTION_LONG_DESCRIPTION = """
Use the `python_execution` tool to run Python code for data analysis, computation, visualization, and file processing.

**Capabilities:**
- Data analysis with pandas, numpy, scipy
- Data visualization with matplotlib
- Image processing with PIL
- File generation (CSV, plots, processed data)
- Mathematical computations

**Limitations:**
- No internet access (cannot make HTTP requests, download files)
- Maximum execution time enforced
- Isolated environment (no persistent state between executions)

**Available Libraries:**
numpy, pandas, scipy, matplotlib, PIL, and other common data science libraries.

**File Handling:**
- Files generated by your code (saved to disk) will be automatically captured and returned
- Generated files can include plots, CSVs, processed images, etc.
- Files are available for download by the user
"""
```

### 6. Database Migration

**Create Alembic Migration** to seed the `PythonTool` in the database:

Similar to `d09fc20a3c66_seed_builtin_tools.py`, create a new migration that:
```python
def upgrade() -> None:
    """Add PythonTool to built-in tools"""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Check if tool already exists
    existing_tool = session.execute(
        select(Tool).where(Tool.in_code_tool_id == "PythonTool")
    ).first()

    if not existing_tool:
        python_tool = Tool(
            name="Python Execution",
            description="Execute Python code in a secure, isolated environment",
            in_code_tool_id="PythonTool",
        )
        session.add(python_tool)
        session.commit()
```

### 7. Testing Strategy

**External Dependency Unit Tests** (`backend/tests/external_dependency_unit/tools/test_python_tool.py`):

Test with real Code Interpreter service running (no mocking of service):
```python
def test_python_execution_basic():
    """Test basic Python execution with simple code"""
    # Execute: print("Hello, World!")
    # Assert: stdout contains "Hello, World!", exit_code is 0

def test_python_execution_with_error():
    """Test Python execution with syntax/runtime error"""
    # Execute: invalid syntax or division by zero
    # Assert: stderr contains error, exit_code is non-zero

def test_python_execution_timeout():
    """Test execution timeout handling"""
    # Execute: infinite loop with short timeout
    # Assert: timed_out is True

def test_python_execution_file_generation():
    """Test file generation and retrieval"""
    # Execute: create CSV file, save to disk
    # Assert: generated_files contains file, file can be downloaded

def test_python_execution_with_matplotlib():
    """Test matplotlib plot generation"""
    # Execute: create matplotlib plot, save as PNG
    # Assert: generated_files contains PNG, file is valid image

def test_python_execution_context_updates():
    """Test that run_context is properly updated"""
    # Execute: simple code
    # Assert: iteration_instructions and global_iteration_responses updated
    # Assert: current_run_step incremented correctly

def test_python_tool_availability():
    """Test PythonTool.is_available() classmethod"""
    # Test with CODE_INTERPRETER_BASE_URL set
    # Assert: is_available() returns True
    # Test with CODE_INTERPRETER_BASE_URL unset (or empty string)
    # Assert: is_available() returns False
```

### 8. Default Assistant Page Integration

**Update** `backend/onyx/server/features/default_assistant/api.py`:
```python
# Import PythonTool at the top
from onyx.tools.tool_implementations.python.python_tool import PythonTool

# In the list_available_tools endpoint, add PythonTool to ORDERED_TOOL_IDS:
ORDERED_TOOL_IDS = [
    SearchTool.__name__,
    WebSearchTool.__name__,
    ImageGenerationTool.__name__,
    PythonTool.__name__,  # Add this line
]
```

**Update** `web/src/app/admin/configuration/default-assistant/page.tsx`:
```typescript
// In the ToolCard component's notEnabledReason logic (around line 265):
const notEnabledReason = (() => {
  if (tool.in_code_tool_id === "WebSearchTool") {
    return "Set EXA_API_KEY on the server and restart to enable Web Search.";
  }
  if (tool.in_code_tool_id === "ImageGenerationTool") {
    return "Add an OpenAI LLM provider with an API key under Admin → Configuration → LLM.";
  }
  if (tool.in_code_tool_id === "PythonTool") {
    return "Set CODE_INTERPRETER_BASE_URL on the server and restart to enable Python Execution.";
  }
  return "Not configured.";
})();
```

**Update** `web/src/app/chat/components/tools/constants.ts`:
```typescript
// Add Python tool constants:
export const PYTHON_TOOL_NAME = "run_python";
export const PYTHON_TOOL_ID = "PythonTool";

// Add to SYSTEM_TOOL_ICONS:
export const SYSTEM_TOOL_ICONS: Record<
  string,
  React.FunctionComponent<SvgProps>
> = {
  [SEARCH_TOOL_ID]: SvgSearch,
  [WEB_SEARCH_TOOL_ID]: SvgGlobe,
  [IMAGE_GENERATION_TOOL_ID]: SvgImage,
  [PYTHON_TOOL_ID]: SvgCode,  // Add this line
};
```

### 9. Frontend Integration (Brief Overview)

**Streaming Packet Handlers:**
- Add handlers for `PythonToolStart` and `PythonToolDelta` packet types
- Display stdout/stderr in real-time during execution
- Show loading state while code executes
- When `PythonToolDelta` arrives with `file_ids`, display file attachments
  - Follow the same pattern as `CustomToolDelta` which also uses `file_ids: list[str]`
  - Files can be fetched via existing file download endpoints using the file IDs
- `SectionEnd` packet signals completion (emitted by `@tool_accounting` decorator)

**File Display:**
- Generated files should appear as downloadable attachments
- Image files (PNG, JPG) should display inline
- CSV/text files should offer download option
- Use same UI components as custom tool file handling

**Tool Selection UI:**
- Tool appears in default assistant page with availability status
- Tool will appear/disappear based on whether `CODE_INTERPRETER_BASE_URL` is configured
- Shows "Not enabled" badge with helpful tooltip when unavailable

### 10. Migration & Rollout

**Phase 1: Backend Core (Weeks 1-2)**
1. **Implement chat file access infrastructure (Step 0)** - Update ChatTurnContext, fast_chat_turn, and process_message
2. Add configuration and service client
3. Create `PythonTool` wrapper class for availability checking
4. Implement core v2 tool function with basic execution
5. Add streaming models and result models
6. Write external dependency unit tests

**Phase 2: File Handling (Week 3)**
7. Implement file upload/download workflow
8. Add file generation and retrieval logic
9. Test with matplotlib plots and CSV files
10. Expand external dependency tests for file handling

**Phase 3: Integration (Week 4)**
11. Create Alembic migration to seed `PythonTool` in database
12. Update `built_in_tools.py` to register `PythonTool` in `BUILT_IN_TOOL_MAP`
13. **Update `built_in_tools_v2.py` to register `python_execution` in `BUILT_IN_TOOL_MAP_V2`** (critical - enables v2 agent to execute the tool)
14. **Add PythonTool instantiation in `tool_constructor.py`** (critical - prevents "No tools found" errors)
15. Update default assistant API and frontend for Python tool
16. Verify availability checking works correctly (URL configured vs. not configured)
17. Add frontend packet handlers
18. Manual testing with real service

**Phase 4: Polish & Documentation (Week 5)**
19. Add error handling improvements
20. Write user-facing documentation
21. Add admin documentation for service deployment
22. Performance testing and optimization
23. Test tool availability UI (tool should appear/disappear based on `CODE_INTERPRETER_BASE_URL` configuration)

## Implementation Decisions

1. **File Input Handling:** Automatically pass all files from the chat to the Python execution environment. Files will be staged in the workspace before execution.

2. **Timeout Configuration:** Fixed timeout per deployment controlled via `CODE_INTERPRETER_DEFAULT_TIMEOUT_MS` environment variable. LLM cannot override timeout.

3. **Security & Sandboxing:** Docker isolation is sufficient. No additional memory, disk, or CPU limits required beyond what's configured at the Docker level.

4. **Library Availability:** Tool description mentions only core libraries: `numpy, pandas, scipy, matplotlib, PIL`. Don't provide exhaustive list to LLM - let it discover other available libraries through experimentation.

5. **State Persistence:** No stateful execution. Each tool call is completely isolated with a fresh workspace. No persistence between calls.

6. **Large Output Handling:** Truncate stdout/stderr for LLM consumption at a configurable limit via `CODE_INTERPRETER_MAX_OUTPUT_LENGTH` environment variable. Full output is not separately stored.

## Success Criteria

- [ ] Python code executes successfully in isolated environment
- [ ] Execution results (stdout, stderr, exit code) returned to LLM
- [ ] Generated files (plots, CSVs, etc.) captured and downloadable
- [ ] Timeouts enforced and handled gracefully
- [ ] Real-time streaming updates during execution
- [ ] Comprehensive test coverage (external dependency tests)
- [ ] Frontend displays execution results and files correctly
- [ ] Error messages are clear and actionable
- [ ] Documentation complete for admins and users
