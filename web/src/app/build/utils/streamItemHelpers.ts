/**
 * Stream Item Helpers
 *
 * Shared utility functions for processing ACP packets into StreamItems.
 * Used by both useBuildStreaming (live streaming) and useBuildSessionStore (loading from DB).
 */

import {
  ToolCallKind,
  ToolCallStatus,
  TodoItem,
  TodoStatus,
} from "@/app/build/types/displayTypes";

// =============================================================================
// ID Generation
// =============================================================================

/**
 * Generate a unique ID for stream items
 */
export function genId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// =============================================================================
// Text Extraction
// =============================================================================

/**
 * Extract text from ACP content structure
 */
export function extractText(content: unknown): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (typeof content === "object" && content !== null) {
    const obj = content as Record<string, unknown>;
    if (obj.type === "text" && typeof obj.text === "string") return obj.text;
    if (Array.isArray(content)) {
      return content
        .filter((c) => c?.type === "text" && typeof c.text === "string")
        .map((c) => c.text)
        .join("");
    }
    if (typeof obj.text === "string") return obj.text;
  }
  return "";
}

// =============================================================================
// Tool Detection
// =============================================================================

/**
 * Check if a tool is a task/subagent tool
 * Detects both by tool name ("task") and by presence of subagent_type in rawInput
 * (needed because backend changes title to description on completion)
 */
export function isTaskTool(
  toolNameOrPacket: string | null | undefined | Record<string, unknown>
): boolean {
  if (typeof toolNameOrPacket === "string" || toolNameOrPacket == null) {
    return toolNameOrPacket?.toLowerCase() === "task";
  }

  // It's a packet - check tool name first
  const toolName = (
    (toolNameOrPacket.tool_name ||
      toolNameOrPacket.toolName ||
      toolNameOrPacket.title) as string | undefined
  )?.toLowerCase();

  if (toolName === "task") return true;

  // Also check for subagent_type in rawInput (present even when title changes)
  const rawInput = (toolNameOrPacket.raw_input ||
    toolNameOrPacket.rawInput) as Record<string, unknown> | null;
  if (rawInput?.subagent_type || rawInput?.subagentType) return true;

  return false;
}

/**
 * Check if a tool call should be included in a "Working" pill.
 * Returns true for all tool calls except task/subagent tools.
 * Working tools: glob, grep, read, edit, write, bash, webfetch, websearch, etc.
 */
export function isWorkingToolCall(toolCall: {
  kind: string;
  subagentType?: string;
}): boolean {
  // Task tools (subagents) are kept as separate pills
  if (toolCall.kind === "task") return false;
  if (toolCall.subagentType) return false;
  return true;
}

/**
 * Check if a tool is a TodoWrite tool.
 * Detects by tool name ("todowrite", "todo_write") OR by presence of todos array in rawInput.
 * The second check is needed because the backend may change the title on completion
 * (e.g., from "todowrite" to "6 todos").
 */
export function isTodoWriteTool(
  toolNameOrPacket: string | null | undefined | Record<string, unknown>
): boolean {
  let toolName: string | undefined;

  if (typeof toolNameOrPacket === "object" && toolNameOrPacket !== null) {
    // It's a packet - extract tool name
    toolName = (
      (toolNameOrPacket.tool_name ||
        toolNameOrPacket.toolName ||
        toolNameOrPacket.title) as string | undefined
    )?.toLowerCase();

    // Also check for todos array in rawInput (present even when title changes)
    const rawInput = (toolNameOrPacket.raw_input ||
      toolNameOrPacket.rawInput) as Record<string, unknown> | null;
    if (rawInput?.todos && Array.isArray(rawInput.todos)) {
      return true;
    }
  } else {
    // It's a string (or null/undefined)
    toolName = toolNameOrPacket?.toLowerCase();
  }

  return toolName === "todowrite" || toolName === "todo_write";
}

// =============================================================================
// Tool Title & Kind
// =============================================================================

/**
 * Get human-readable title based on tool kind and name
 * @param isNewFile - For "edit" kind: true = new file (Writing), false = existing file (Editing)
 */
export function getToolTitle(
  kind: string | null | undefined,
  toolName: string | null | undefined,
  isNewFile?: boolean
): string {
  // Special case: "edit" kind uses isNewFile to determine title
  // The title field often contains the file path (not "edit"), so we can't rely on toolName
  if (kind === "edit") {
    return isNewFile === false ? "Editing " : "Writing ";
  }

  const normalizedToolName = toolName?.toLowerCase();

  // Priority 1: Check tool name for specific mappings (most specific)
  if (normalizedToolName) {
    switch (normalizedToolName) {
      case "task":
        return "Running task";
      case "glob":
        return "Searching files";
      case "grep":
        return "Searching content";
      case "webfetch":
        return "Fetching web content";
      case "websearch":
        return "Searching web";
      case "bash":
        return "Running command";
      case "read":
        return "Read ";
      case "write":
      case "edit":
        return "Writing ";
    }
  }

  // Priority 2: Fall back to kind-based titles
  switch (kind) {
    case "execute":
      return "Running command";
    case "read":
      return "Read ";
    case "task":
      return "Running task";
    case "search":
      return "Searching";
    case "other":
    default:
      return "Running tool";
  }
}

/**
 * Normalize tool call kind
 */
export function normalizeKind(
  kind: string | null | undefined,
  toolNameOrPacket?: string | null | Record<string, unknown>
): ToolCallKind {
  // Task tool is identified by tool name or subagent_type
  if (isTaskTool(toolNameOrPacket)) return "task";
  if (
    kind === "execute" ||
    kind === "read" ||
    kind === "task" ||
    kind === "other"
  )
    return kind;
  return "other";
}

/**
 * Normalize tool call status
 */
export function normalizeStatus(
  status: string | null | undefined
): ToolCallStatus {
  if (
    status === "pending" ||
    status === "in_progress" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled"
  ) {
    return status;
  }
  return "pending";
}

// =============================================================================
// Tool Call Data Extraction
// =============================================================================

/**
 * Strip sandbox path prefix to get clean relative path
 * Handles various path formats:
 * - /outputs/... → extracts path after /outputs/
 * - /data/sandboxes/[id]/sessions/[id]/... → extracts path after session ID
 * - /sandboxes/[id]/sessions/[id]/... → extracts path after session ID
 * - /sandboxes/[id]/... → extracts path after sandbox ID
 * - Otherwise → extracts filename
 */
export function getRelativePath(fullPath: string): string {
  if (!fullPath) return "";

  // 1. Check for /outputs/ prefix
  const outputsMatch = fullPath.match(/\/outputs\/(.+)$/);
  if (outputsMatch?.[1]) return outputsMatch[1];

  // 2. Check for /data/sandboxes/[id]/sessions/[id]/... pattern
  const dataSandboxSessionMatch = fullPath.match(
    /\/data\/sandboxes\/[^/]+\/sessions\/[^/]+\/(.+)$/
  );
  if (dataSandboxSessionMatch?.[1]) return dataSandboxSessionMatch[1];

  // 3. Check for /sandboxes/[id]/sessions/[id]/... pattern
  const sandboxSessionMatch = fullPath.match(
    /\/sandboxes\/[^/]+\/sessions\/[^/]+\/(.+)$/
  );
  if (sandboxSessionMatch?.[1]) return sandboxSessionMatch[1];

  // 4. Check for /sandboxes/[id]/... pattern
  const sandboxMatch = fullPath.match(/\/sandboxes\/[^/]+\/(.+)$/);
  if (sandboxMatch?.[1]) return sandboxMatch[1];

  // 5. Fallback: extract filename (everything after last slash)
  const lastSlash = fullPath.lastIndexOf("/");
  return lastSlash >= 0 ? fullPath.slice(lastSlash + 1) : fullPath;
}

/**
 * Extract file path from packet (for read/write tools)
 */
export function getFilePath(packet: Record<string, unknown>): string {
  // 1. Check rawInput for explicit file_path
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  if (rawInput) {
    const path = (rawInput.file_path || rawInput.filePath || rawInput.path) as
      | string
      | undefined;
    if (path) return getRelativePath(path);
  }

  // 2. Check content array for diff items (edit packets store path in diff)
  const content = packet.content as unknown[] | undefined;
  if (Array.isArray(content)) {
    for (const item of content) {
      if (
        item &&
        typeof item === "object" &&
        (item as Record<string, unknown>).type === "diff"
      ) {
        const diffPath = (item as Record<string, unknown>).path as
          | string
          | undefined;
        if (diffPath) return getRelativePath(diffPath);
      }
    }
  }

  // 3. Fall back to title (often contains file path for edit packets)
  const title = packet.title as string | undefined;
  if (title && title.includes("/")) return getRelativePath(title);
  return "";
}

/**
 * Extract description from tool call packet
 */
export function getDescription(packet: Record<string, unknown>): string {
  const kind = packet.kind as string | null;
  const normalizedKind = kind === "edit" ? "other" : kind;
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();

  // Task tool: use description from rawInput
  // Pass full packet to detect task tools even when title changes on completion
  if (isTaskTool(packet)) {
    if (rawInput?.description && typeof rawInput.description === "string") {
      return rawInput.description;
    }
    return "Running subagent";
  }

  if (normalizedKind === "read" || normalizedKind === "other") {
    const filePath = getFilePath(packet);
    if (filePath) return filePath;
  }

  if (normalizedKind === "execute") {
    if (rawInput?.description && typeof rawInput.description === "string") {
      return rawInput.description;
    }
    return "Running command";
  }

  if (
    (toolName === "glob" ||
      toolName === "grep" ||
      normalizedKind === "search") &&
    rawInput?.pattern &&
    typeof rawInput.pattern === "string"
  ) {
    return rawInput.pattern;
  }

  return getToolTitle(kind, toolName);
}

/**
 * Extract command/path from tool call packet
 */
export function getCommand(packet: Record<string, unknown>): string {
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  const kind = packet.kind as string | null;
  const normalizedKind = kind === "edit" ? "other" : kind;
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();

  // Task tool: use prompt from rawInput
  // Pass full packet to detect task tools even when title changes on completion
  if (isTaskTool(packet) && rawInput) {
    if (typeof rawInput.prompt === "string") return rawInput.prompt;
    return "";
  }

  if (normalizedKind === "execute" && rawInput) {
    if (typeof rawInput.command === "string") return rawInput.command;
  }

  if (normalizedKind === "read" || normalizedKind === "other") {
    return getFilePath(packet);
  }

  if (
    (toolName === "glob" ||
      toolName === "grep" ||
      normalizedKind === "search") &&
    rawInput?.pattern &&
    typeof rawInput.pattern === "string"
  ) {
    return rawInput.pattern;
  }

  return "";
}

/**
 * Extract file content from content array (for read operations)
 */
export function extractFileContent(content: unknown): string {
  if (!Array.isArray(content)) return "";

  for (const item of content) {
    if (item?.type === "content" && item?.content?.type === "text") {
      const text = item.content.text as string;
      const fileMatch = text.match(
        /<file>\n?([\s\S]*?)\n?\(End of file[^)]*\)\n?<\/file>/
      );
      if (fileMatch && fileMatch[1]) {
        return fileMatch[1].replace(/^\d{5}\| /gm, "");
      }
      return text;
    }
  }
  return "";
}

/**
 * Extract newText from content array (for write operations)
 */
export function extractNewText(content: unknown): string {
  if (!Array.isArray(content)) return "";

  for (const item of content) {
    if (item?.type === "diff" && typeof item?.newText === "string") {
      return item.newText;
    }
  }
  return "";
}

/**
 * Extract oldText from content array (for edit operations)
 */
export function extractOldText(content: unknown): string {
  if (!Array.isArray(content)) return "";

  for (const item of content) {
    if (item?.type === "diff" && typeof item?.oldText === "string") {
      return item.oldText;
    }
  }
  return "";
}

/**
 * Extract both old and new text from content array for edit operations.
 * Returns { oldText, newText, isNewFile } where isNewFile is true if oldText is empty.
 */
export function extractDiffData(content: unknown): {
  oldText: string;
  newText: string;
  isNewFile: boolean;
} {
  const oldText = extractOldText(content);
  const newText = extractNewText(content);
  return {
    oldText,
    newText,
    isNewFile: oldText === "",
  };
}

/**
 * Check if an edit packet represents a new file (write) vs editing existing file.
 * Returns true if it's a new file, false if editing existing, undefined if not applicable.
 */
export function isNewFileOperation(
  packet: Record<string, unknown>
): boolean | undefined {
  const kind = packet.kind as string | null;
  if (kind !== "edit") return undefined;

  const content = packet.content;
  const oldText = extractOldText(content);
  return oldText === "";
}

/**
 * Extract subagent type from task tool packet
 */
export function getSubagentType(
  packet: Record<string, unknown>
): string | undefined {
  const rawInput = (packet.raw_input || packet.rawInput) as Record<
    string,
    unknown
  > | null;
  if (rawInput?.subagent_type && typeof rawInput.subagent_type === "string") {
    return rawInput.subagent_type;
  }
  if (rawInput?.subagentType && typeof rawInput.subagentType === "string") {
    return rawInput.subagentType;
  }
  return undefined;
}

/**
 * Extract task output text from completed task tool packet
 * Returns the output text if present, null otherwise
 */
export function getTaskOutput(packet: Record<string, unknown>): string | null {
  if (!isTaskTool(packet)) return null;

  const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
    string,
    unknown
  > | null;

  if (rawOutput?.output && typeof rawOutput.output === "string") {
    // Strip task_metadata from the output
    let output = rawOutput.output;
    const metadataIndex = output.indexOf("<task_metadata>");
    if (metadataIndex >= 0) {
      output = output.slice(0, metadataIndex).trim();
    }
    return output;
  }

  return null;
}

/**
 * Extract raw output from tool call packet
 */
export function getRawOutput(packet: Record<string, unknown>): string {
  const kind = packet.kind as string | null;
  const normalizedKind = kind === "edit" ? "other" : kind;
  const toolName = (
    (packet.tool_name || packet.toolName || packet.title) as string | undefined
  )?.toLowerCase();

  // Task tool: show the prompt in expanded view (not the output JSON)
  // Pass full packet to detect task tools even when title changes on completion
  if (isTaskTool(packet)) {
    const rawInput = (packet.raw_input || packet.rawInput) as Record<
      string,
      unknown
    > | null;
    if (rawInput?.prompt && typeof rawInput.prompt === "string") {
      return rawInput.prompt;
    }
    // Don't fall back to rawOutput JSON - keep showing the prompt
    return "";
  }

  if (normalizedKind === "execute") {
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    if (!rawOutput) return "";
    const metadata = rawOutput.metadata as Record<string, unknown> | null;
    return (metadata?.output || rawOutput.output || "") as string;
  }

  if (normalizedKind === "read") {
    const content = packet.content;
    const fileContent = extractFileContent(content);
    if (fileContent) return fileContent;
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    if (!rawOutput) return "";
    if (typeof rawOutput.content === "string") return rawOutput.content;
    return JSON.stringify(rawOutput, null, 2);
  }

  if (normalizedKind === "other") {
    const content = packet.content;
    const newText = extractNewText(content);
    if (newText) return newText;
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    if (!rawOutput) return "";
    return JSON.stringify(rawOutput, null, 2);
  }

  if (
    toolName === "glob" ||
    toolName === "grep" ||
    normalizedKind === "search"
  ) {
    const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
      string,
      unknown
    > | null;
    if (!rawOutput) return "";
    if (typeof rawOutput.output === "string") {
      return rawOutput.output;
    }
    if (rawOutput.files && Array.isArray(rawOutput.files)) {
      return (rawOutput.files as string[]).join("\n");
    }
    return JSON.stringify(rawOutput, null, 2);
  }

  const rawOutput = (packet.raw_output || packet.rawOutput) as Record<
    string,
    unknown
  > | null;
  if (!rawOutput) return "";
  return JSON.stringify(rawOutput, null, 2);
}

// =============================================================================
// Todo List Helpers
// =============================================================================

/**
 * Normalize todo status to valid TodoStatus type
 */
export function normalizeTodoStatus(status: unknown): TodoStatus {
  if (
    status === "pending" ||
    status === "in_progress" ||
    status === "completed"
  ) {
    return status;
  }
  return "pending";
}

/**
 * Extract todos from TodoWrite packet (works with both packet and metadata)
 */
export function extractTodos(
  packetOrMetadata: Record<string, unknown>
): TodoItem[] {
  const rawInput = (packetOrMetadata.raw_input ||
    packetOrMetadata.rawInput) as Record<string, unknown> | null;
  if (!rawInput?.todos || !Array.isArray(rawInput.todos)) return [];

  return rawInput.todos.map((t: Record<string, unknown>) => ({
    content: (t.content as string) || "",
    status: normalizeTodoStatus(t.status),
    activeForm: (t.activeForm as string) || (t.content as string) || "",
  }));
}
