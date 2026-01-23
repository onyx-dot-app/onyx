# Packet Processing Refactor Plan

This document outlines a comprehensive refactor of `streamItemHelpers.ts` to cleanly determine packet types and extract relevant information.

---

## Current Problems

### 1. Scattered Type Detection
The current code has type detection logic spread across multiple functions:
- `isTodoWriteTool()` checks tool name in multiple places
- `isTaskTool()` checks tool name separately
- `normalizeKind()` has mixed tool name and kind logic
- Each extraction function (`getDescription`, `getCommand`, etc.) re-checks the kind/tool name

### 2. Inconsistent Field Access
Field names vary between snake_case and camelCase with no central mapping:
- `tool_call_id` vs `toolCallId`
- `raw_input` vs `rawInput`
- `raw_output` vs `rawOutput`
- `tool_name` vs `toolName` vs `title`

### 3. Mixed Concerns
Helper functions mix:
- Packet type identification
- Field extraction
- Display formatting
- Path sanitization

### 4. No Type Safety
Packets are typed as `Record<string, unknown>` with repeated casting throughout.

---

## Proposed Architecture

### Layer 1: Packet Parsing (Type-Safe)

Create a discriminated union type for all packets:

```typescript
// packets.ts - New file

// ============================================================================
// Core Types
// ============================================================================

export type PacketType =
  | "agent_message_chunk"
  | "agent_thought_chunk"
  | "tool_call_start"
  | "tool_call_progress"
  | "agent_plan_update"
  | "prompt_response"
  | "artifact_created"
  | "error"
  | "unknown";

export type ToolName =
  | "glob"
  | "grep"
  | "read"
  | "write"
  | "edit"
  | "bash"
  | "task"
  | "todowrite"
  | "webfetch"
  | "websearch"
  | "unknown";

export type ToolKind = "search" | "read" | "execute" | "edit" | "task" | "other";

// ============================================================================
// Parsed Packet Types (Discriminated Union)
// ============================================================================

export interface ParsedMessageChunk {
  type: "agent_message_chunk" | "agent_thought_chunk";
  text: string;
}

export interface ParsedToolCallStart {
  type: "tool_call_start";
  toolCallId: string;
  toolName: ToolName;
  kind: ToolKind;
}

export interface ParsedToolCallProgress {
  type: "tool_call_progress";
  toolCallId: string;
  toolName: ToolName;
  kind: ToolKind;
  status: "pending" | "in_progress" | "completed" | "failed" | "cancelled";
  input: ToolInput;
  output: ToolOutput | null;
  locations: LocationInfo[];
}

export interface ParsedPlanUpdate {
  type: "agent_plan_update";
  entries: PlanEntry[];
}

export interface ParsedPromptResponse {
  type: "prompt_response";
  stopReason: "end_turn" | "max_tokens" | "stop_sequence";
}

export interface ParsedArtifact {
  type: "artifact_created";
  artifact: ArtifactInfo;
}

export interface ParsedError {
  type: "error";
  message: string;
}

export interface ParsedUnknown {
  type: "unknown";
  raw: unknown;
}

export type ParsedPacket =
  | ParsedMessageChunk
  | ParsedToolCallStart
  | ParsedToolCallProgress
  | ParsedPlanUpdate
  | ParsedPromptResponse
  | ParsedArtifact
  | ParsedError
  | ParsedUnknown;
```

### Layer 2: Tool-Specific Input/Output Types

```typescript
// ============================================================================
// Tool Input Types (Discriminated by toolName)
// ============================================================================

export type ToolInput =
  | { toolName: "glob"; pattern: string }
  | { toolName: "grep"; pattern: string; path?: string }
  | { toolName: "read"; filePath: string }
  | { toolName: "write"; filePath: string; content: string }
  | { toolName: "edit"; filePath: string; oldString: string; newString: string }
  | { toolName: "bash"; command: string; description: string }
  | { toolName: "task"; prompt: string; description: string; subagentType: string }
  | { toolName: "todowrite"; todos: TodoItem[] }
  | { toolName: "webfetch"; url: string; prompt: string }
  | { toolName: "websearch"; query: string }
  | { toolName: "unknown"; raw: unknown };

// ============================================================================
// Tool Output Types
// ============================================================================

export interface SearchOutput {
  files: string[];
  count: number;
  truncated: boolean;
}

export interface ReadOutput {
  content: string;
  truncated: boolean;
}

export interface WriteOutput {
  success: boolean;
  newText?: string;
  oldText?: string;        // Empty string for new files, content for edits
  isNewFile: boolean;      // true = new file (write), false = edit existing
}

export interface BashOutput {
  output: string;
  exitCode: number;
  truncated: boolean;
}

export interface TodoOutput {
  todos: TodoItem[];
}

export type ToolOutput =
  | { toolName: "glob" | "grep"; data: SearchOutput }
  | { toolName: "read"; data: ReadOutput }
  | { toolName: "write" | "edit"; data: WriteOutput }
  | { toolName: "bash"; data: BashOutput }
  | { toolName: "task"; data: { result: string } }
  | { toolName: "todowrite"; data: TodoOutput }
  | { toolName: "unknown"; data: unknown };
```

### Layer 3: Parsing Functions

```typescript
// packetParser.ts - New file

// ============================================================================
// Main Parser
// ============================================================================

export function parsePacket(raw: unknown): ParsedPacket {
  if (!raw || typeof raw !== "object") {
    return { type: "unknown", raw };
  }

  const packet = raw as Record<string, unknown>;
  const packetType = determinePacketType(packet);

  switch (packetType) {
    case "agent_message_chunk":
    case "agent_thought_chunk":
      return parseMessageChunk(packet, packetType);
    case "tool_call_start":
      return parseToolCallStart(packet);
    case "tool_call_progress":
      return parseToolCallProgress(packet);
    case "agent_plan_update":
      return parsePlanUpdate(packet);
    case "prompt_response":
      return parsePromptResponse(packet);
    case "artifact_created":
      return parseArtifact(packet);
    case "error":
      return parseError(packet);
    default:
      return { type: "unknown", raw };
  }
}

// ============================================================================
// Type Determination
// ============================================================================

function determinePacketType(packet: Record<string, unknown>): PacketType {
  // Check explicit type field first
  const type = packet.type as string | undefined;
  if (type === "agent_message_chunk") return "agent_message_chunk";
  if (type === "agent_thought_chunk") return "agent_thought_chunk";
  if (type === "tool_call_progress") return "tool_call_progress";
  if (type === "agent_plan_update") return "agent_plan_update";
  if (type === "prompt_response") return "prompt_response";
  if (type === "artifact_created") return "artifact_created";
  if (type === "error") return "error";

  // Fall back to sessionUpdate field
  const sessionUpdate = packet.sessionUpdate as string | undefined;
  if (sessionUpdate === "agent_message_chunk") return "agent_message_chunk";
  if (sessionUpdate === "tool_call") return "tool_call_start";
  if (sessionUpdate === "tool_call_update") return "tool_call_progress";
  if (sessionUpdate === "plan") return "agent_plan_update";

  return "unknown";
}

// ============================================================================
// Tool Name Normalization
// ============================================================================

function normalizeToolName(packet: Record<string, unknown>): ToolName {
  const name = (
    packet.tool_name ??
    packet.toolName ??
    packet.title ??
    ""
  ) as string;

  const normalized = name.toLowerCase();

  switch (normalized) {
    case "glob": return "glob";
    case "grep": return "grep";
    case "read": return "read";
    case "write": return "write";
    case "edit": return "edit";
    case "bash": return "bash";
    case "task": return "task";
    case "todowrite":
    case "todo_write": return "todowrite";
    case "webfetch": return "webfetch";
    case "websearch": return "websearch";
    default: return "unknown";
  }
}

function toolNameToKind(toolName: ToolName, rawKind?: string): ToolKind {
  // Task is always identified by name, not kind
  if (toolName === "task") return "task";

  // Tool-specific mappings
  switch (toolName) {
    case "glob":
    case "grep":
      return "search";
    case "read":
      return "read";
    case "write":
    case "edit":
      return "edit";
    case "bash":
      return "execute";
    default:
      // Fall back to rawKind if provided
      if (rawKind === "search" || rawKind === "read" || rawKind === "execute" || rawKind === "edit") {
        return rawKind;
      }
      return "other";
  }
}
```

### Layer 4: Display Helpers (Pure)

```typescript
// displayHelpers.ts - Replaces most of current streamItemHelpers.ts

// ============================================================================
// Display Formatting (No parsing, just formatting)
// ============================================================================

/**
 * Get human-readable title for a tool call
 * @param isNewFile - For edit/write tools: true = new file, false = editing existing
 */
export function getToolDisplayTitle(toolName: ToolName, isNewFile?: boolean): string {
  // Special handling for edit kind - distinguish between write and edit
  if (toolName === "write" || toolName === "edit") {
    return isNewFile === false ? "Editing file" : "Writing file";
  }

  const titles: Record<ToolName, string> = {
    glob: "Searching files",
    grep: "Searching content",
    read: "Reading file",
    write: "Writing file",
    edit: "Editing file",
    bash: "Running command",
    task: "Running task",
    todowrite: "Updating todos",
    webfetch: "Fetching web content",
    websearch: "Searching web",
    unknown: "Running tool",
  };
  return titles[toolName];
}

/**
 * Get description text for a tool call
 */
export function getToolDescription(input: ToolInput): string {
  switch (input.toolName) {
    case "glob":
    case "grep":
      return input.pattern;
    case "read":
    case "write":
    case "edit":
      return getRelativePath(input.filePath);
    case "bash":
      return input.description || "Running command";
    case "task":
      return input.description || "Running subagent";
    case "todowrite":
      return `${input.todos.length} todos`;
    case "webfetch":
      return input.prompt;
    case "websearch":
      return input.query;
    default:
      return "";
  }
}

/**
 * Get command/detail text for expanded view
 */
export function getToolCommand(input: ToolInput): string {
  switch (input.toolName) {
    case "glob":
    case "grep":
      return input.pattern;
    case "read":
    case "write":
    case "edit":
      return getRelativePath(input.filePath);
    case "bash":
      return input.command;
    case "task":
      return input.prompt;
    default:
      return "";
  }
}

/**
 * Format output for display
 */
export function formatToolOutput(output: ToolOutput | null): string {
  if (!output) return "";

  switch (output.toolName) {
    case "glob":
    case "grep":
      return output.data.files.join("\n");
    case "read":
      return output.data.content;
    case "write":
    case "edit":
      return output.data.newText ?? "";
    case "bash":
      return output.data.output;
    case "task":
      return output.data.result;
    case "todowrite":
      return JSON.stringify(output.data.todos, null, 2);
    default:
      return JSON.stringify(output.data, null, 2);
  }
}

/**
 * Strip sandbox path prefix to get clean relative path
 */
export function getRelativePath(fullPath: string): string {
  if (!fullPath) return "";
  const outputsMatch = fullPath.match(/\/outputs\/(.+)$/);
  if (outputsMatch?.[1]) return outputsMatch[1];
  const sandboxMatch = fullPath.match(/\/sandboxes\/[^/]+\/(.+)$/);
  if (sandboxMatch?.[1]) return sandboxMatch[1];
  const lastSlash = fullPath.lastIndexOf("/");
  return lastSlash >= 0 ? fullPath.slice(lastSlash + 1) : fullPath;
}
```

---

## Migration Plan

### Phase 1: Create New Files
1. Create `packets.ts` with all type definitions
2. Create `packetParser.ts` with parsing functions
3. Create `displayHelpers.ts` with formatting functions

### Phase 2: Update Consumers
Update in order:
1. `useBuildStreaming.ts` - Use `parsePacket()` in SSE handler
2. `useBuildSessionStore.ts` - Use `parsePacket()` in `convertMessagesToStreamItems()`

### Phase 3: Clean Up
1. Delete redundant functions from `streamItemHelpers.ts`
2. Keep only utilities that are still needed:
   - `genId()` - ID generation
   - `normalizeTodoStatus()` - Used by display components
3. Update imports across codebase

---

## Example: Refactored useBuildStreaming Handler

```typescript
import { parsePacket, ParsedPacket } from "@/app/build/utils/packetParser";
import { getToolDisplayTitle, getToolDescription, getToolCommand, formatToolOutput } from "@/app/build/utils/displayHelpers";

// In processSSEStream callback:
await processSSEStream(response, (rawPacket) => {
  const packet = parsePacket(rawPacket);

  switch (packet.type) {
    case "agent_message_chunk":
      handleTextChunk(sessionId, packet.text);
      break;

    case "agent_thought_chunk":
      handleThinkingChunk(sessionId, packet.text);
      break;

    case "tool_call_start": {
      // Simple, clean handling
      if (packet.toolName === "todowrite") {
        appendTodoList(sessionId, packet.toolCallId);
      } else {
        appendToolCall(sessionId, {
          id: packet.toolCallId,
          kind: packet.kind,
          title: getToolDisplayTitle(packet.toolName),
          status: "pending",
          description: "",
          command: "",
          rawOutput: "",
          subagentType: packet.toolName === "task" ? undefined : undefined,
        });
      }
      break;
    }

    case "tool_call_progress": {
      if (packet.toolName === "todowrite" && packet.input.toolName === "todowrite") {
        updateTodoList(sessionId, packet.toolCallId, packet.input.todos);
      } else {
        updateToolCall(sessionId, packet.toolCallId, {
          status: packet.status,
          description: getToolDescription(packet.input),
          command: getToolCommand(packet.input),
          rawOutput: formatToolOutput(packet.output),
          subagentType: packet.input.toolName === "task" ? packet.input.subagentType : undefined,
        });
      }
      break;
    }

    case "agent_plan_update":
      // Handle plan updates if needed
      break;

    case "prompt_response":
      finalizeStreaming();
      updateSessionData(sessionId, { status: "completed" });
      break;

    case "error":
      updateSessionData(sessionId, {
        status: "failed",
        error: packet.message,
      });
      break;
  }
});
```

---

## Benefits

1. **Type Safety**: Discriminated unions catch errors at compile time
2. **Single Source of Truth**: Packet type determined once in `parsePacket()`
3. **Separation of Concerns**:
   - Parsing (raw → typed)
   - Display formatting (typed → strings)
4. **Testability**: Each layer can be unit tested independently
5. **Maintainability**: Adding new tool types is straightforward
6. **Readability**: Switch statements on discriminated unions are self-documenting

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `utils/packets.ts` | CREATE | Type definitions |
| `utils/packetParser.ts` | CREATE | Parsing functions |
| `utils/displayHelpers.ts` | CREATE | Formatting functions |
| `utils/streamItemHelpers.ts` | MODIFY | Keep only `genId()`, `normalizeTodoStatus()` |
| `hooks/useBuildStreaming.ts` | MODIFY | Use new parser |
| `hooks/useBuildSessionStore.ts` | MODIFY | Use new parser in `convertMessagesToStreamItems()` |

---

## Discovered Quirks (Session 2026-01-22)

### 1. Title Field Changes on Completion

For certain tools, the `title` field changes between `tool_call_start` and `tool_call_progress`:

| Tool | Start `title` | Completed `title` |
|------|---------------|-------------------|
| TodoWrite | `"todowrite"` | `"6 todos"` (count-based) |
| Edit/Write | `"edit"` or `"write"` | File path (e.g., `"path/to/file.tsx"`) |

**Solution:** Don't rely solely on `title` for tool identification. Check `rawInput` for tool-specific fields:
- TodoWrite: `rawInput.todos` array exists
- Task: `rawInput.subagent_type` exists
- Edit: Check `kind === "edit"` field

### 2. Write vs Edit Detection

The backend sends `kind: "edit"` for both new file creation and editing existing files. The distinction is in the diff content:

| `content[].oldText` | Operation | Display |
|---------------------|-----------|---------|
| `""` (empty string) | New file  | "Writing file" |
| Non-empty string    | Edit      | "Editing file" |

**Extraction Function:**
```typescript
function extractDiffData(content: unknown): {
  oldText: string;
  newText: string;
  isNewFile: boolean;
} {
  if (!Array.isArray(content)) return { oldText: "", newText: "", isNewFile: true };

  for (const item of content) {
    if (item?.type === "diff") {
      const oldText = item.oldText || "";
      const newText = item.newText || "";
      return { oldText, newText, isNewFile: oldText === "" };
    }
  }
  return { oldText: "", newText: "", isNewFile: true };
}
```

### 3. File Path Extraction for Edit Packets

For `kind: "edit"` packets, the file path can be in multiple locations:

1. `rawInput.file_path` / `rawInput.filePath` / `rawInput.path`
2. `content[].path` (in diff items)
3. `title` field (contains full path on completion)

---

## Current Implementation Status

As of 2026-01-22, the following has been implemented in `streamItemHelpers.ts`:

### Implemented Functions
- `isTodoWriteTool()` - Detects by title OR `rawInput.todos` array
- `isTaskTool()` - Detects by title OR `rawInput.subagent_type`
- `isNewFileOperation()` - Checks `kind === "edit"` and `content[].oldText`
- `extractDiffData()` - Returns `{ oldText, newText, isNewFile }`
- `extractOldText()` / `extractNewText()` - Extract from diff content
- `getToolTitle()` - Now accepts optional `isNewFile` parameter
- `getFilePath()` - Checks rawInput → content[].diff.path → title

### ToolCallState Extended Fields
```typescript
interface ToolCallState {
  // ... existing fields ...
  isNewFile?: boolean;     // true = new file, false = editing existing
  oldContent?: string;     // Old content (empty for new files)
  newContent?: string;     // New content
}
```

### DiffView Component
Created `components/DiffView.tsx` for displaying diffs:
- Green highlighting for added lines (+)
- Red highlighting for removed lines (-)
- Collapsible unchanged sections
- Stats header showing +N / -M lines

### ToolCallPill Updates
- Shows `DiffView` for "Editing file" operations
- Shows `RawOutputBlock` for "Writing file" and other operations
