# ACP Packet Types Reference

This document defines the JSON structure for every packet type used in the Build streaming protocol.

---

## 1. agent_message_chunk

Streaming text content from the agent. Chunks arrive sequentially and should be concatenated.

```typescript
interface AgentMessageChunkPacket {
  _meta: null;
  type: "agent_message_chunk";
  sessionUpdate: "agent_message_chunk";
  content: {
    _meta: null;
    type: "text";
    text: string;           // The text fragment
    annotations: null;
  };
}
```

**Example:**
```json
{
  "_meta": null,
  "content": {
    "_meta": null,
    "annotations": null,
    "text": "I'll help you create",
    "type": "text"
  },
  "sessionUpdate": "agent_message_chunk",
  "type": "agent_message_chunk"
}
```

---

## 2. tool_call_start

Signals the beginning of a tool invocation. Contains initial metadata but no results yet.

```typescript
interface ToolCallStartPacket {
  _meta: null;
  type: "tool_call_start";              // NOTE: Not present in actual packets
  sessionUpdate: "tool_call";           // Discriminator in actual packets

  // Tool identification
  toolCallId: string;                   // Unique ID for this tool invocation
  title: string;                        // Tool name: "glob", "read", "bash", "write", "todowrite"
  kind: ToolCallKind;                   // "search" | "read" | "execute" | "edit" | "other"

  // Initial state
  status: "pending";
  content: null;
  rawInput: {};                         // Empty initially
  rawOutput: null;
  locations: [];                        // Empty initially
}

type ToolCallKind = "search" | "read" | "execute" | "edit" | "other";
```

**Example (Glob):**
```json
{
  "_meta": null,
  "content": null,
  "kind": "search",
  "locations": [],
  "rawInput": {},
  "rawOutput": null,
  "status": "pending",
  "title": "glob",
  "toolCallId": "toolu_01JQPzZLN1GkctYVgpaaxD8X",
  "sessionUpdate": "tool_call"
}
```

**Example (TodoWrite):**
```json
{
  "_meta": null,
  "content": null,
  "kind": "other",
  "locations": [],
  "rawInput": {},
  "rawOutput": null,
  "status": "pending",
  "title": "todowrite",
  "toolCallId": "toolu_01RcpWgYMMtMch3XPebkLwcp",
  "sessionUpdate": "tool_call"
}
```

---

## 3. tool_call_progress

Updates for an in-progress or completed tool call. Contains full input/output when complete.

```typescript
interface ToolCallProgressPacket {
  _meta: null;
  type: "tool_call_progress";
  sessionUpdate: "tool_call_update";
  timestamp: string;                    // ISO 8601 timestamp

  // Tool identification
  toolCallId: string;
  title: string;                        // Updates to description on completion
  kind: ToolCallKind;

  // State
  status: "in_progress" | "completed";

  // Input (populated when status changes to in_progress or completed)
  rawInput: ToolRawInput;

  // Output (populated when status is completed)
  rawOutput: ToolRawOutput | null;
  content: ToolContentArray | null;

  // File locations (for read/edit tools)
  locations: LocationInfo[] | null;
}
```

### 3.1 Tool-Specific rawInput Shapes

**Glob/Grep (search):**
```typescript
interface GlobInput {
  pattern: string;           // e.g., "files/linear/**/*.json"
}

interface GrepInput {
  pattern: string;           // Search pattern
  path?: string;             // Directory to search
}
```

**Read:**
```typescript
interface ReadInput {
  filePath: string;          // Full path to file
}
```

**Write/Edit:**
```typescript
interface WriteInput {
  filePath: string;
  content: string;           // File content to write
}

interface EditInput {
  filePath: string;
  old_string: string;
  new_string: string;
}
```

**Bash (execute):**
```typescript
interface BashInput {
  command: string;           // Shell command
  description: string;       // Human-readable description
}
```

**Task (subagent):**
```typescript
interface TaskInput {
  prompt: string;            // Task prompt for subagent
  description: string;       // Short description
  subagent_type: string;     // "Explore", "Plan", "Bash", etc.
}
```

**TodoWrite:**
```typescript
interface TodoWriteInput {
  todos: TodoItem[];
}

interface TodoItem {
  content: string;           // Task description
  status: "pending" | "in_progress" | "completed";
  activeForm: string;        // Present tense form (e.g., "Creating API endpoint")
}
```

### 3.2 Tool-Specific rawOutput Shapes

**Glob/Grep:**
```typescript
interface SearchOutput {
  output: string;            // Newline-separated file paths or "No files found"
  metadata: {
    count: number;
    truncated: boolean;
  };
}
```

**Read:**
```typescript
interface ReadOutput {
  output: string;            // File content wrapped in <file>...</file> tags
  metadata: {
    preview: string;         // First N characters
    truncated: boolean;
  };
}
```

**Bash:**
```typescript
interface BashOutput {
  output: string;            // Command output
  metadata: {
    output: string;          // Same as parent output
    exit: number;            // Exit code
    description: string;     // From input
    truncated: boolean;
  };
}
```

**Write:**
```typescript
interface WriteOutput {
  output: string;            // "Wrote file successfully."
  metadata: {
    diagnostics: Record<string, unknown[]>;
    filepath: string;
    exists: boolean;
    truncated: boolean;
  };
}
```

**TodoWrite:**
```typescript
interface TodoWriteOutput {
  output: string;            // JSON array of todos
  metadata: {
    todos: TodoItem[];       // Same as input todos
    truncated: boolean;
  };
}
```

### 3.3 Content Array Structure

The `content` field contains structured output for rendering:

```typescript
type ToolContentArray = ContentItem[];

interface ContentItem {
  _meta: null;
  type: "content" | "diff";

  // For type: "content"
  content?: {
    _meta: null;
    type: "text";
    text: string;
    annotations: null;
  };

  // For type: "diff" (write operations)
  newText?: string;
  oldText?: string;
  path?: string;
}
```

**Example (Read result):**
```json
{
  "content": [
    {
      "_meta": null,
      "type": "content",
      "content": {
        "_meta": null,
        "type": "text",
        "text": "<file>\n00001| {content}\n...\n</file>",
        "annotations": null
      }
    }
  ]
}
```

**Example (Write result - NEW file):**
```json
{
  "content": [
    {
      "_meta": null,
      "type": "content",
      "content": {
        "_meta": null,
        "type": "text",
        "text": "Wrote file successfully.",
        "annotations": null
      }
    },
    {
      "_meta": null,
      "type": "diff",
      "newText": "// new file content...",
      "oldText": "",
      "path": "/path/to/file.ts"
    }
  ]
}
```

**Example (Edit result - EXISTING file):**
```json
{
  "content": [
    {
      "_meta": null,
      "type": "content",
      "content": {
        "_meta": null,
        "type": "text",
        "text": "Wrote file successfully.",
        "annotations": null
      }
    },
    {
      "_meta": null,
      "type": "diff",
      "newText": "const x = 2;\nconst y = 3;",
      "oldText": "const x = 1;",
      "path": "/path/to/file.ts"
    }
  ]
}
```

### 3.4 Write vs Edit Detection

The `oldText` field in diff content items distinguishes between new file creation and editing existing files:

| `oldText` value | Operation | Display Title |
|-----------------|-----------|---------------|
| `""` (empty)    | New file  | "Writing file" |
| Non-empty       | Edit      | "Editing file" |

**Detection Logic:**
```typescript
function isNewFileOperation(packet: Record<string, unknown>): boolean | undefined {
  if (packet.kind !== "edit") return undefined;

  const content = packet.content as unknown[] | undefined;
  if (!Array.isArray(content)) return undefined;

  for (const item of content) {
    if (item?.type === "diff") {
      return item.oldText === "";
    }
  }
  return undefined;
}
```

**Important Notes:**
- For `kind: "edit"` packets, the `title` field contains the **file path**, not the tool name
- Detection must check both `kind` field AND `oldText` in the diff content
- The backend persists `kind: "edit"` for both write and edit operations

### 3.5 Locations Array

```typescript
interface LocationInfo {
  _meta: null;
  path: string;              // File path
  line: number | null;       // Line number (if applicable)
}
```

---

## 4. agent_plan_update

Signals updates to the agent's todo/plan list. Separate from tool_call_progress for TodoWrite.

```typescript
interface AgentPlanUpdatePacket {
  _meta: null;
  type: "agent_plan_update";
  sessionUpdate: "plan";
  timestamp: string;
  entries: PlanEntry[];
}

interface PlanEntry {
  _meta: null;
  content: string;           // Task description
  status: "pending" | "in_progress" | "completed";
  priority: "medium" | "high" | "low";
}
```

**Example:**
```json
{
  "_meta": null,
  "entries": [
    {
      "_meta": null,
      "content": "Create prepare.sh script",
      "priority": "medium",
      "status": "completed"
    },
    {
      "_meta": null,
      "content": "Build dashboard page",
      "priority": "medium",
      "status": "in_progress"
    }
  ],
  "sessionUpdate": "plan",
  "type": "agent_plan_update",
  "timestamp": "2026-01-22T19:13:30.917345+00:00"
}
```

---

## 5. prompt_response

Signals the end of the agent's response turn.

```typescript
interface PromptResponsePacket {
  _meta: {};                 // Note: empty object, not null
  type: "prompt_response";
  stopReason: "end_turn" | "max_tokens" | "stop_sequence";
}
```

**Example:**
```json
{
  "_meta": {},
  "stopReason": "end_turn",
  "type": "prompt_response"
}
```

---

## 6. error

Error packet for streaming failures.

```typescript
interface ErrorPacket {
  type: "error";
  message: string;
  code?: string;
}
```

---

## 7. artifact_created

Signals creation of a new artifact (file, webapp, etc.).

```typescript
interface ArtifactCreatedPacket {
  type: "artifact_created";
  artifact: {
    id: string;
    type: ArtifactType;
    name: string;
    path: string;
    preview_url?: string | null;
  };
}

type ArtifactType = "file" | "image" | "nextjs_app" | "web_app";
```

---

## Packet Type Determination

To determine packet type, check in this order:

1. Check `type` field if present
2. Check `sessionUpdate` field:
   - `"agent_message_chunk"` → agent_message_chunk
   - `"tool_call"` → tool_call_start
   - `"tool_call_update"` → tool_call_progress
   - `"plan"` → agent_plan_update

---

## Tool Name to Kind Mapping

| Tool Name     | kind      | Description                    |
|---------------|-----------|--------------------------------|
| `glob`        | search    | File pattern matching          |
| `grep`        | search    | Content search                 |
| `read`        | read      | Read file contents             |
| `write`       | edit      | Write new file                 |
| `edit`        | edit      | Edit existing file             |
| `bash`        | execute   | Run shell command              |
| `task`        | task*     | Spawn subagent                 |
| `todowrite`   | other     | Update todo list               |
| `webfetch`    | other     | Fetch web content              |
| `websearch`   | other     | Search the web                 |

*Note: `task` kind is determined by tool name, not the `kind` field.

---

## Known Quirks & Detection Strategies

### Title Field Changes on Completion

For some tools, the `title` field changes between `tool_call_start` and `tool_call_progress`:

| Tool | Start `title` | Completed `title` |
|------|---------------|-------------------|
| TodoWrite | `"todowrite"` | `"6 todos"` (count-based) |
| Edit/Write | `"edit"` or `"write"` | File path (e.g., `"path/to/file.tsx"`) |

**Detection Strategy:**
- Don't rely solely on `title` for tool identification
- Check `rawInput` for tool-specific fields:
  - TodoWrite: `rawInput.todos` array exists
  - Task: `rawInput.subagent_type` exists
  - Edit: Check `kind === "edit"` field

### Tool Detection Functions

```typescript
// Detect TodoWrite even when title changes
function isTodoWriteTool(packet: Record<string, unknown>): boolean {
  const title = packet.title?.toLowerCase();
  if (title === "todowrite" || title === "todo_write") return true;

  // Fallback: check rawInput for todos array
  const rawInput = packet.raw_input || packet.rawInput;
  if (rawInput?.todos && Array.isArray(rawInput.todos)) return true;

  return false;
}

// Detect Task tool even when title changes
function isTaskTool(packet: Record<string, unknown>): boolean {
  const title = packet.title?.toLowerCase();
  if (title === "task") return true;

  // Fallback: check rawInput for subagent_type
  const rawInput = packet.raw_input || packet.rawInput;
  if (rawInput?.subagent_type || rawInput?.subagentType) return true;

  return false;
}
```

### Field Path Extraction for Edit Packets

For `kind: "edit"` packets, the file path can be found in multiple locations (checked in order):

1. `rawInput.file_path` or `rawInput.filePath` or `rawInput.path`
2. `content[].path` (in diff items)
3. `title` field (contains full path on completion)

```typescript
function getFilePath(packet: Record<string, unknown>): string {
  // 1. Check rawInput
  const rawInput = packet.raw_input || packet.rawInput;
  if (rawInput?.file_path || rawInput?.filePath || rawInput?.path) {
    return getRelativePath(rawInput.file_path || rawInput.filePath || rawInput.path);
  }

  // 2. Check content array for diff items
  if (Array.isArray(packet.content)) {
    for (const item of packet.content) {
      if (item?.type === "diff" && item?.path) {
        return getRelativePath(item.path);
      }
    }
  }

  // 3. Fall back to title
  if (packet.title?.includes("/")) {
    return getRelativePath(packet.title);
  }

  return "";
}
```
