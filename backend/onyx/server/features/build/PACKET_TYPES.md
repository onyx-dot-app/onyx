# Build Mode Packet Types

This document describes the packet types used for streaming agent responses in Onyx Build Mode.

## Overview

The Build Mode streaming API uses Server-Sent Events (SSE) to stream agent responses to the frontend. All packets are sent as `event: message` with a JSON payload containing a `type` field to distinguish packet types.

The packet system is based on:
- **Agent Client Protocol (ACP)**: https://agentclientprotocol.com
- **OpenCode ACP Implementation**: https://github.com/agentclientprotocol/python-sdk

## Packet Categories

### 1. Step/Thinking Packets

Track the agent's internal reasoning process.

#### `step_start`
Begin a logical step in agent processing.

```json
{
  "type": "step_start",
  "step_id": "planning",
  "step_name": "Planning Implementation",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

#### `step_delta`
Progress within a step (agent's internal reasoning).

```json
{
  "type": "step_delta",
  "step_id": "thinking",
  "content": "I need to first understand the codebase structure...",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `AgentThoughtChunk` from ACP

#### `step_end`
Finish a step.

```json
{
  "type": "step_end",
  "step_id": "planning",
  "status": "completed",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

### 2. Tool Call Packets

Track tool invocations and their results.

#### `tool_start`
Agent invoking a tool.

```json
{
  "type": "tool_start",
  "tool_call_id": "tc_123",
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/path/to/file.py"
  },
  "title": "Reading file.py",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `ToolCallStart` from ACP

#### `tool_progress`
Tool execution progress update.

```json
{
  "type": "tool_progress",
  "tool_call_id": "tc_123",
  "tool_name": "Bash",
  "status": "in_progress",
  "progress": 0.5,
  "message": "Running tests...",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

#### `tool_end`
Tool execution finished.

```json
{
  "type": "tool_end",
  "tool_call_id": "tc_123",
  "tool_name": "Read",
  "status": "success",
  "result": "File contents here...",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `ToolCallProgress` from ACP

### 3. Agent Output Packets

Track the agent's text responses.

#### `output_start`
Begin agent's text output.

```json
{
  "type": "output_start",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

#### `output_delta`
Incremental agent text output.

```json
{
  "type": "output_delta",
  "content": "I've updated the file to include...",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `AgentMessageChunk` from ACP

#### `output_end`
Agent's text output finished.

```json
{
  "type": "output_end",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

### 4. Plan Packets

Track the agent's execution plan.

#### `plan`
Agent's execution plan.

```json
{
  "type": "plan",
  "plan": "1. Read the file\n2. Make changes\n3. Run tests",
  "entries": [
    {
      "id": "1",
      "description": "Read the file",
      "status": "pending",
      "priority": 1
    }
  ],
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `AgentPlanUpdate` from ACP

### 5. Mode Update Packets

Track agent mode changes (e.g., planning, implementing, debugging).

#### `mode_update`
Agent mode change.

```json
{
  "type": "mode_update",
  "mode": "implement",
  "description": "Starting implementation",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `CurrentModeUpdate` from ACP

### 6. Completion Packets

Signal task completion.

#### `done`
Signal completion with summary.

```json
{
  "type": "done",
  "summary": "Task completed successfully",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 1000,
    "output_tokens": 500
  },
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Stop Reasons:**
- `end_turn`: Agent completed normally
- `max_tokens`: Hit token limit
- `max_turn_requests`: Hit max tool calls
- `refusal`: Agent refused the request
- `cancelled`: User cancelled

**Source:** `PromptResponse` from ACP

### 7. Error Packets

Report errors.

#### `error`
An error occurred.

```json
{
  "type": "error",
  "message": "Failed to read file: File not found",
  "code": -1,
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Source:** `Error` from ACP

### 8. Custom Onyx Packets

Onyx-specific packets not part of ACP.

#### `file_write`
File written to sandbox.

```json
{
  "type": "file_write",
  "path": "outputs/file.py",
  "size_bytes": 1024,
  "operation": "create",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

#### `artifact_created`
New artifact generated.

```json
{
  "type": "artifact_created",
  "artifact": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "web_app",
    "name": "Web Application",
    "path": "outputs/web/",
    "preview_url": "/api/build/sessions/{session_id}/preview",
    "download_url": "/api/build/sessions/{session_id}/artifacts/outputs/web/",
    "mime_type": "text/html",
    "size_bytes": 4096
  },
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

**Artifact Types:**
- `web_app`: Web application
- `markdown`: Markdown document
- `image`: Image file
- `csv`: CSV/Excel file (displayed as CSV in UI)
- `excel`: Excel spreadsheet
- `pptx`: PowerPoint presentation
- `docx`: Word document
- `pdf`: PDF document
- `code`: Code file
- `other`: Other file type

### 9. Permission Packets

Request and respond to user permissions (future use).

#### `permission_request`
Request user permission for an operation.

```json
{
  "type": "permission_request",
  "request_id": "pr_123",
  "operation": "delete_file",
  "description": "Delete test.py?",
  "auto_approve": false,
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

#### `permission_response`
Response to a permission request.

```json
{
  "type": "permission_response",
  "request_id": "pr_123",
  "approved": true,
  "reason": "User approved",
  "timestamp": "2025-01-20T12:00:00.000Z"
}
```

## Content Block Types

All content in ACP can be sent as structured content blocks:

### Text Content
```json
{
  "type": "text",
  "text": "Hello world"
}
```

### Image Content
```json
{
  "type": "image",
  "data": "base64-encoded-image-data",
  "mimeType": "image/png"
}
```

### Audio Content
```json
{
  "type": "audio",
  "data": "base64-encoded-audio-data",
  "mimeType": "audio/wav"
}
```

### Embedded Resource
```json
{
  "type": "embedded_resource",
  "uri": "file:///path/to/file",
  "text": "Resource contents...",
  "mimeType": "text/plain"
}
```

### Resource Link
```json
{
  "type": "resource_link",
  "uri": "file:///path/to/file",
  "name": "file.txt",
  "mimeType": "text/plain",
  "size": 1024
}
```

## Usage in Code

### Converting ACP Events to Packets

Use the conversion utilities in `build_packet_types.py`:

```python
from onyx.server.features.build.build_packet_types import (
    convert_acp_thought_to_step_delta,
    convert_acp_tool_start_to_tool_start,
    convert_acp_tool_progress_to_tool_end,
    convert_acp_message_chunk_to_output_delta,
    convert_acp_plan_to_plan,
    convert_acp_mode_update_to_mode_update,
    convert_acp_prompt_response_to_done,
    convert_acp_error_to_error,
)

# Convert ACP event to packet
if isinstance(acp_event, AgentThoughtChunk):
    packet = convert_acp_thought_to_step_delta(acp_event)
    yield packet
```

### Creating Artifacts

```python
from onyx.server.features.build.build_packet_types import (
    create_artifact_from_file,
    ArtifactType,
    ArtifactCreatedPacket,
)

artifact = create_artifact_from_file(
    session_id=session_id,
    file_path="outputs/web/",
    artifact_type=ArtifactType.WEB_APP,
    name="Web Application",
)
packet = ArtifactCreatedPacket(artifact=artifact)
yield packet
```

### Formatting Packets for SSE

```python
def _format_packet_event(packet: BuildPacket) -> str:
    """Format a packet as SSE (all events use event: message)."""
    return f"event: message\ndata: {packet.model_dump_json(by_alias=True)}\n\n"

# Use in streaming
yield _format_packet_event(packet)
```

## Type Safety

All packet types are Pydantic models with full type safety:

```python
from onyx.server.features.build.build_packet_types import (
    BuildPacket,
    StepDeltaPacket,
    ToolStartPacket,
    OutputDeltaPacket,
)

# Type-safe packet creation
packet: StepDeltaPacket = StepDeltaPacket(
    step_id="thinking",
    content="Analyzing the code..."
)

# Union type for all packets
def process_packet(packet: BuildPacket) -> None:
    if isinstance(packet, StepDeltaPacket):
        print(f"Thinking: {packet.content}")
    elif isinstance(packet, ToolStartPacket):
        print(f"Using tool: {packet.tool_name}")
```

## References

- Agent Client Protocol: https://agentclientprotocol.com
- ACP Prompt Turn: https://agentclientprotocol.com/protocol/prompt-turn
- ACP Content Blocks: https://agentclientprotocol.com/protocol/content
- OpenCode Python SDK: https://github.com/agentclientprotocol/python-sdk
