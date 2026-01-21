# ACP Data Capture - Full Field Documentation

## Overview

The backend now captures **ALL** fields from ACP (Agent Client Protocol) events and streams them directly to the frontend. This ensures complete transparency and allows the frontend to access any ACP data it needs.

## Backend Changes

### 1. Full Field Serialization
**File:** `messages_api.py:138-153`

Changed from `exclude_none=True` to `exclude_none=False` to capture ALL fields:

```python
def _serialize_acp_event(event: Any, event_type: str) -> str:
    """Serialize an ACP event to SSE format, preserving ALL ACP data."""
    if hasattr(event, "model_dump"):
        data = event.model_dump(mode="json", by_alias=True, exclude_none=False)
    else:
        data = {"raw": str(event)}

    data["type"] = event_type
    data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

    return f"event: message\ndata: {json.dumps(data)}\n\n"
```

### 2. Timestamp Addition
All ACP events now include a `timestamp` field for frontend tracking.

## ACP Events and Their Fields

### agent_message_chunk (AgentMessageChunk)
Agent's text/content output chunks during streaming.

**Fields:**
- `content`: ContentBlock (text, image, audio, resource, etc.)
- `field_meta`: Optional metadata dictionary (_meta in ACP)
- `session_update`: "agent_message_chunk"
- `timestamp`: ISO 8601 timestamp (added by Onyx)

**Example:**
```json
{
  "type": "agent_message_chunk",
  "content": {
    "type": "text",
    "text": "I'll create a React app for you..."
  },
  "field_meta": null,
  "session_update": "agent_message_chunk",
  "timestamp": "2026-01-20T20:56:34.123Z"
}
```

### agent_thought_chunk (AgentThoughtChunk)
Agent's internal reasoning/thinking process.

**Fields:**
- `content`: ContentBlock
- `field_meta`: Optional metadata
- `session_update`: "agent_thought_chunk"
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "agent_thought_chunk",
  "content": {
    "type": "text",
    "text": "Let me analyze the requirements..."
  },
  "field_meta": null,
  "session_update": "agent_thought_chunk",
  "timestamp": "2026-01-20T20:56:34.456Z"
}
```

### tool_call_start (ToolCallStart)
Indicates the agent is starting to use a tool.

**Fields:**
- `tool_call_id`: Unique ID for this tool invocation
- `kind`: Tool category (e.g., "edit", "execute", "other")
- `title`: Human-readable description of what the tool does
- `content`: ContentBlock with tool description/info
- `locations`: Array of file paths/locations affected
- `raw_input`: Original input parameters to the tool
- `raw_output`: Output (usually null at start)
- `status`: Tool status (usually null/pending at start)
- `field_meta`: Optional metadata
- `session_update`: Tool update type
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "tool_call_start",
  "tool_call_id": "call_abc123",
  "kind": "edit",
  "title": "Write file /app/page.tsx",
  "content": {
    "type": "text",
    "text": "Creating React component..."
  },
  "locations": ["/app/page.tsx"],
  "raw_input": {
    "path": "/app/page.tsx",
    "content": "..."
  },
  "raw_output": null,
  "status": null,
  "field_meta": null,
  "session_update": "tool_call_start",
  "timestamp": "2026-01-20T20:56:35.789Z"
}
```

### tool_call_progress (ToolCallProgress)
Progress update or completion of a tool call.

**Fields:**
- `tool_call_id`: ID matching the tool_call_start
- `kind`: Tool category
- `title`: Tool title
- `content`: ContentBlock with progress/result info
- `locations`: File paths affected
- `raw_input`: Original input
- `raw_output`: Tool execution result
- `status`: "in_progress", "completed", "failed", etc.
- `field_meta`: Optional metadata
- `session_update`: Tool update type
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "tool_call_progress",
  "tool_call_id": "call_abc123",
  "kind": "edit",
  "title": "Write file /app/page.tsx",
  "content": {
    "type": "text",
    "text": "File written successfully"
  },
  "locations": ["/app/page.tsx"],
  "raw_input": {...},
  "raw_output": {
    "success": true,
    "bytes_written": 1234
  },
  "status": "completed",
  "field_meta": null,
  "session_update": "tool_call_progress",
  "timestamp": "2026-01-20T20:56:36.012Z"
}
```

### agent_plan_update (AgentPlanUpdate)
Agent's execution plan with structured task list.

**Fields:**
- `entries`: Array of plan entries, each with:
  - `id`: Task ID
  - `description`: Task description
  - `status`: "pending", "in_progress", "completed", "cancelled"
  - `priority`: String ("high", "medium", "low") or number
- `field_meta`: Optional metadata
- `session_update`: "agent_plan_update"
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "agent_plan_update",
  "entries": [
    {
      "id": "task_1",
      "description": "Set up Next.js project structure",
      "status": "completed",
      "priority": "high"
    },
    {
      "id": "task_2",
      "description": "Create React components",
      "status": "in_progress",
      "priority": "medium"
    }
  ],
  "field_meta": null,
  "session_update": "agent_plan_update",
  "timestamp": "2026-01-20T20:56:37.345Z"
}
```

### current_mode_update (CurrentModeUpdate)
Agent switched to a different mode (e.g., coding mode, planning mode).

**Fields:**
- `current_mode_id`: New mode identifier
- `field_meta`: Optional metadata
- `session_update`: "current_mode_update"
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "current_mode_update",
  "current_mode_id": "coding",
  "field_meta": null,
  "session_update": "current_mode_update",
  "timestamp": "2026-01-20T20:56:38.678Z"
}
```

### prompt_response (PromptResponse)
Agent finished processing the user's request.

**Fields:**
- `stop_reason`: Why the agent stopped ("end_turn", "max_tokens", "refusal", etc.)
- `field_meta`: Optional metadata
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "prompt_response",
  "stop_reason": "end_turn",
  "field_meta": null,
  "timestamp": "2026-01-20T20:56:39.901Z"
}
```

### error (ACPError)
An error occurred during agent execution.

**Fields:**
- `code`: Error code (string or null)
- `message`: Human-readable error message
- `data`: Additional error context/data
- `timestamp`: ISO 8601 timestamp

**Example:**
```json
{
  "type": "error",
  "code": "TOOL_EXECUTION_FAILED",
  "message": "Failed to write file: permission denied",
  "data": {
    "path": "/protected/file.txt",
    "errno": "EACCES"
  },
  "timestamp": "2026-01-20T20:56:40.234Z"
}
```

## Frontend TypeScript Types

All ACP packet types are now properly typed in `buildStreamingModels.ts`:

```typescript
// Raw ACP packets with ALL fields
export type StreamPacket =
  | AgentMessageChunkPacket
  | AgentThoughtChunkPacket
  | ToolCallStartPacket
  | ToolCallProgressPacket
  | AgentPlanUpdatePacket
  | CurrentModeUpdatePacket
  | PromptResponsePacket
  | ACPErrorPacket
  | ... // Custom Onyx packets
```

## Key Benefits

1. **Complete Transparency**: All ACP data is available to the frontend
2. **Future-Proof**: New ACP fields automatically flow through
3. **Debugging**: Full event data logged on backend for troubleshooting
4. **Extensibility**: `field_meta` allows custom metadata without protocol changes
5. **Type Safety**: Full TypeScript types for all ACP events

## Logging

All ACP events are logged with their complete structure:

```python
logger.warning(
    f"[STREAM] Event #{event_count}: {event_type} = {json.dumps(event_data, default=str)[:500]}"
)
```

This helps with debugging and understanding what data is flowing through the system.

## Custom Onyx Packets

In addition to raw ACP events, Onyx sends custom packets:

- `artifact_created`: New artifact generated (web app, file, etc.)
- `file_write`: File written to sandbox
- `error`: Onyx-specific errors (e.g., session not found)

These use the same SSE format and include timestamps.
