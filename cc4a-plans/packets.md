# Build Mode Packet Types Overview

This document describes all packet types received from the `/sessions/{session_id}/send-message` endpoint. These packets are streamed via Server-Sent Events (SSE) and follow the Agent Client Protocol (ACP) specification.

## Packet Delivery Format

All packets are delivered as SSE events:
```
event: message
data: { ... JSON payload ... }
```

Each packet includes:
- `type`: String identifier for the packet type
- `timestamp`: ISO 8601 timestamp (added by backend)

---

## Packet Types Summary

| Packet Type | Source | Purpose |
|-------------|--------|---------|
| `agent_message_chunk` | ACP | Streaming text content from the agent |
| `tool_call_start` | ACP | Tool invocation started (pending state) |
| `tool_call_progress` | ACP | Tool execution updates and results |
| `prompt_response` | ACP | Agent finished processing the prompt |
| `error` | ACP/Onyx | Error occurred during processing |

---

## 1. `agent_message_chunk`

Streaming text content from the agent. Multiple chunks are sent as the agent generates text token-by-token.

### Structure
```typescript
interface AgentMessageChunk {
  type: "agent_message_chunk";
  sessionUpdate: "agent_message_chunk";
  content: {
    type: "text";
    text: string;        // The text fragment
    annotations: null;
  };
  _meta: null;
}
```

### Frontend Rendering
- Accumulate `content.text` values to build complete message
- Render as markdown (supports GitHub-flavored markdown)
- Display incrementally for streaming effect

### Example
```json
{
  "type": "agent_message_chunk",
  "sessionUpdate": "agent_message_chunk",
  "content": {
    "type": "text",
    "text": "I'll help you ",
    "annotations": null
  },
  "_meta": null
}
```

---

## 2. `tool_call_start`

Signals that a tool invocation has started. Sent when the agent decides to use a tool but before execution begins.

### Structure
```typescript
interface ToolCallStart {
  type: "tool_call_start";
  sessionUpdate: "tool_call";
  toolCallId: string;           // Unique identifier for this tool call
  title: string;                // Tool name: "bash", "read", "apply_patch", etc.
  kind: ToolKind;               // "execute" | "read" | "other"
  status: "pending";            // Always "pending" for start events
  rawInput: {};                 // Empty object at start
  rawOutput: null;
  content: null;
  locations: [];                // Empty at start
  _meta: null;
}

type ToolKind = "execute" | "read" | "other";
```

### Tool Kinds
- `execute`: Command execution (bash commands)
- `read`: File reading operations
- `other`: Patches, writes, and other operations (e.g., `apply_patch`)

### Frontend Rendering
- Create a new tool call UI component
- Show tool name (`title`) with loading indicator
- Display "pending" state

### Example
```json
{
  "type": "tool_call_start",
  "sessionUpdate": "tool_call",
  "toolCallId": "call_2xQlLvWCPjteq7lHJSqBC76p",
  "title": "bash",
  "kind": "execute",
  "status": "pending",
  "rawInput": {},
  "rawOutput": null,
  "content": null,
  "locations": [],
  "_meta": null
}
```

---

## 3. `tool_call_progress`

Updates for tool execution. May be sent multiple times per tool call as status progresses.

### Structure
```typescript
interface ToolCallProgress {
  type: "tool_call_progress";
  sessionUpdate: "tool_call_update";
  toolCallId: string;           // Matches the tool_call_start
  title: string;                // May update with result summary
  kind: ToolKind;
  status: ToolStatus;
  rawInput: ToolInput;          // Tool parameters
  rawOutput: ToolOutput | null; // Execution result (null while in_progress)
  content: ContentBlock[] | null;
  locations: Location[] | null;
  _meta: null;
}

type ToolStatus = "pending" | "in_progress" | "completed" | "failed";

interface Location {
  path: string;
  line: number | null;
  _meta: null;
}

interface ContentBlock {
  type: "content";
  content: {
    type: "text";
    text: string;
    annotations: null;
  };
  _meta: null;
}
```

### Status Progression
1. `pending` → Initial state
2. `in_progress` → Execution started (may receive rawInput)
3. `completed` → Execution finished successfully (has rawOutput)
4. `failed` → Execution failed (rawOutput contains error)

### Tool-Specific Details

#### Bash Tool (`kind: "execute"`)
```typescript
interface BashInput {
  command: string;
  description: string;
}

interface BashOutput {
  output: string;
  metadata: {
    output: string;
    exit: number;
    description: string;
  };
}
```

#### Read Tool (`kind: "read"`)
```typescript
interface ReadInput {
  filePath: string;
}

interface ReadOutput {
  output: string;  // File content with line numbers
  metadata: {
    preview: string;
    truncated: boolean;
  };
}
```

- `locations` array is populated with file path
- Content shows file with line numbers: `00001| import ...`

#### Apply Patch Tool (`kind: "other"`)
```typescript
interface PatchInput {
  patchText: string;  // Unified diff format
}

interface PatchOutput {
  output: string;  // "Success. Updated the following files:\nM path/to/file"
  metadata: {
    diff: string;
    files: FileChange[];
    diagnostics: {};
    truncated: boolean;
  };
}

interface FileChange {
  filePath: string;
  relativePath: string;
  type: "add" | "update";  // "add" for new files, "update" for modifications
  diff: string;            // Unified diff
  before: string;          // Original file content
  after: string;           // New file content
  additions: number;
  deletions: number;
}
```

### Frontend Rendering
- Update tool call UI based on `status`
- For `in_progress`: Show spinner, display command/path from rawInput
- For `completed`:
  - Bash: Show command output, exit code
  - Read: Show file content (consider syntax highlighting)
  - Apply Patch: Show diff view with additions/deletions
- For `failed`: Show error message, display rejection reason if available
- Update `title` as it may contain result summary

### Examples

#### Bash In Progress
```json
{
  "type": "tool_call_progress",
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_2xQlLvWCPjteq7lHJSqBC76p",
  "title": "bash",
  "kind": "execute",
  "status": "in_progress",
  "rawInput": {
    "command": "ls",
    "description": "List repository root contents"
  },
  "rawOutput": null,
  "content": null,
  "locations": []
}
```

#### Bash Completed
```json
{
  "type": "tool_call_progress",
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_2xQlLvWCPjteq7lHJSqBC76p",
  "title": "bash",
  "kind": "execute",
  "status": "completed",
  "rawInput": {
    "command": "ls",
    "description": "List repository root contents"
  },
  "rawOutput": {
    "output": "AGENTS.md\nfiles\nopencode.json\noutputs\nuser_uploaded_files\n",
    "metadata": {
      "output": "AGENTS.md\nfiles\nopencode.json\noutputs\nuser_uploaded_files\n",
      "exit": 0,
      "description": "List repository root contents"
    }
  },
  "content": [
    {
      "type": "content",
      "content": {
        "type": "text",
        "text": "AGENTS.md\nfiles\nopencode.json\noutputs\nuser_uploaded_files\n"
      }
    }
  ],
  "locations": null
}
```

#### Read File Completed
```json
{
  "type": "tool_call_progress",
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_gSGPAsNq5sxtp4mUxOwiTXT4",
  "title": "read",
  "kind": "read",
  "status": "completed",
  "rawInput": {
    "filePath": "/path/to/file.tsx"
  },
  "rawOutput": {
    "output": "<file>\n00001| import Image from \"next/image\";\n00002| \n00003| export default function Home() {\n...</file>",
    "metadata": {
      "preview": "import Image from \"next/image\";\n...",
      "truncated": false
    }
  },
  "content": [
    {
      "type": "content",
      "content": {
        "type": "text",
        "text": "<file>\n00001| import Image from \"next/image\";\n...</file>"
      }
    }
  ],
  "locations": [
    {
      "path": "/path/to/file.tsx",
      "line": null
    }
  ]
}
```

#### Apply Patch Completed (File Update)
```json
{
  "type": "tool_call_progress",
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_WBy9s7I2DgRUnnBxF5jufC3m",
  "title": "Success. Updated the following files:\nM path/to/file.tsx",
  "kind": "other",
  "status": "completed",
  "rawInput": {
    "patchText": "*** Begin Patch\n*** Update File: outputs/web/app/layout.tsx\n@@\n-import { Geist } from \"next/font/google\";\n+import { Spline_Sans } from \"next/font/google\";\n..."
  },
  "rawOutput": {
    "output": "Success. Updated the following files:\nM path/to/file.tsx",
    "metadata": {
      "diff": "Index: /path/to/file.tsx\n===...",
      "files": [
        {
          "filePath": "/full/path/to/file.tsx",
          "relativePath": "path/to/file.tsx",
          "type": "update",
          "diff": "Index: ...",
          "before": "original content...",
          "after": "new content...",
          "additions": 16,
          "deletions": 8
        }
      ],
      "diagnostics": {},
      "truncated": false
    }
  }
}
```

#### Apply Patch Completed (New File)
```json
{
  "type": "tool_call_progress",
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_Lx1wL1PyClxKIyIq1PTDamdj",
  "title": "Success. Updated the following files:\nA path/to/newfile.ts",
  "kind": "other",
  "status": "completed",
  "rawInput": {
    "patchText": "*** Begin Patch\n*** Add File: path/to/newfile.ts\n..."
  },
  "rawOutput": {
    "output": "Success. Updated the following files:\nA path/to/newfile.ts",
    "metadata": {
      "files": [
        {
          "type": "add",
          "before": "",
          "after": "// new file content...",
          "additions": 230,
          "deletions": 0
        }
      ]
    }
  }
}
```

#### Tool Failed (User Rejected)
```json
{
  "type": "tool_call_progress",
  "sessionUpdate": "tool_call_update",
  "toolCallId": "call_anZ06rsTRjTfGiQTapXt970w",
  "title": "bash",
  "kind": "execute",
  "status": "failed",
  "rawInput": {
    "command": "npm run build",
    "description": "Builds the Next.js web app"
  },
  "rawOutput": {
    "error": "Error: The user rejected permission to use this specific tool call."
  }
}
```

---

## 4. `prompt_response`

Signals that the agent has finished processing the current prompt/turn.

### Structure
```typescript
interface PromptResponse {
  type: "prompt_response";
  stopReason: "end_turn";
  _meta: {};
}
```

### Frontend Rendering
- Mark the current message as complete
- Re-enable user input
- Stop any loading indicators

### Example
```json
{
  "type": "prompt_response",
  "stopReason": "end_turn",
  "_meta": {}
}
```

---

## 5. `error`

Error occurred during processing. Can be from ACP (agent errors) or Onyx (infrastructure errors).

### Structure
```typescript
interface ErrorPacket {
  type: "error";
  message: string;
  code: number | null;
  details: Record<string, any> | null;
  timestamp: string;
}
```

### Common Error Types
- Session not found
- Sandbox not running
- Database errors
- Agent execution errors

### Frontend Rendering
- Display error message prominently
- Allow retry if appropriate
- For session/sandbox errors, may need to redirect or refresh

### Example
```json
{
  "type": "error",
  "timestamp": "2026-01-22T00:11:51.712150+00:00",
  "message": "Session not found",
  "code": null,
  "details": null
}
```

---

## Frontend Implementation Notes

### State Management
Track these states per conversation turn:
- `isStreaming`: True while receiving packets
- `toolCalls`: Map of `toolCallId` → tool call state
- `messageContent`: Accumulated text from agent_message_chunk

### Tool Call State Machine
```
pending → in_progress → completed
                     → failed
```

### Recommended UI Components

1. **Message Bubble**: Renders accumulated `agent_message_chunk` text as markdown
2. **Tool Call Card**: Expandable card showing:
   - Tool icon based on `kind` (terminal for execute, file for read, etc.)
   - Tool name from `title`
   - Status indicator (spinner, checkmark, X)
   - Collapsible content showing input/output
3. **Diff Viewer**: For apply_patch results showing before/after with syntax highlighting
4. **Error Banner**: For error packets

### Streaming UX Best Practices
- Show typing indicator while waiting for first chunk
- Render markdown incrementally (may need debouncing)
- Keep tool calls collapsed by default, expand on click
- Auto-scroll to new content but pause if user scrolls up
