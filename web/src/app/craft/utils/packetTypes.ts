/**
 * Packet Types
 *
 * Type definitions for raw and parsed sandbox event packets.
 * Centralizes all snake_case / camelCase field resolution.
 * Defines the ParsedPacket discriminated union consumed by both
 * useBuildStreaming (live SSE) and useBuildSessionStore (DB reload).
 */

import type { TodoItem } from "../types/displayTypes";

// Re-export from displayTypes — single source of truth
export type {
  ToolCallKind as ToolKind,
  ToolCallStatus as ToolStatus,
} from "../types/displayTypes";

// ─── Raw Packet Field Access ─────────────────────────────────────────
// Every backend field name variant is listed ONCE here.

export function getRawInput(
  p: Record<string, unknown>
): Record<string, unknown> | null {
  return (p.raw_input ?? p.rawInput ?? null) as Record<string, unknown> | null;
}

export function getRawOutput(
  p: Record<string, unknown>
): Record<string, unknown> | null {
  return (p.raw_output ?? p.rawOutput ?? null) as Record<
    string,
    unknown
  > | null;
}

export function getToolCallId(p: Record<string, unknown>): string {
  return (p.tool_call_id ?? p.toolCallId ?? "") as string;
}

export function getToolNameRaw(p: Record<string, unknown>): string {
  // Prefer explicit tool_name fields
  const explicit = (p.tool_name ?? p.toolName ?? "") as string;
  if (explicit) return explicit.toLowerCase();

  // ACP _meta is the extensibility slot. The opencode-serve translator
  // stuffs the raw opencode tool name in here (since ACP's strict pydantic
  // schema drops unknown top-level fields).
  const meta = p._meta as Record<string, unknown> | undefined;
  if (meta && typeof meta === "object") {
    const fromMeta = (meta.toolName ?? meta.tool_name ?? "") as string;
    if (fromMeta) return fromMeta.toLowerCase();
  }

  // Fall back to title only if it looks like a simple tool name
  // (no spaces or newlines — otherwise it's a human-readable description)
  const title = (p.title ?? "") as string;
  if (title && !title.includes(" ") && !title.includes("\n")) {
    return title.toLowerCase();
  }

  return "";
}

// ─── Parsed Packet Types (Discriminated Union) ──────────────────────

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
  // opencode 1.15.x additions:
  | "lsp"
  | "apply_patch"
  | "skill"
  | "list"
  | "question"
  | "invalid"
  | "unknown";

export interface ParsedTextChunk {
  type: "text_chunk";
  text: string;
  /** Opencode session this event was emitted on — child's id for subagent child events, else null. */
  sessionId: string | null;
  /** Non-null only for subagent child events — the parent opencode session. */
  parentSessionId: string | null;
}

export interface ParsedThinkingChunk {
  type: "thinking_chunk";
  text: string;
  /** Opencode session this event was emitted on — child's id for subagent child events, else null. */
  sessionId: string | null;
  /** Non-null only for subagent child events — the parent opencode session. */
  parentSessionId: string | null;
}

export interface ParsedToolCallStart {
  type: "tool_call_start";
  toolCallId: string;
  toolName: ToolName;
  kind: import("../types/displayTypes").ToolCallKind;
  isTodo: boolean;
  /** Best-effort title resolved from toolName/kind, shown until progress arrives. */
  title: string;
  /** Display description resolved from rawInput, used before progress arrives. */
  description: string;
  /** Command or task prompt resolved from rawInput, used before progress arrives. */
  command: string;
  skillName: string | null;
  /** For task tool calls: the subagent type, when provided. */
  subagentType: string | null;
  /** Opencode session this event was emitted on — child's id for subagent child events, else null. */
  sessionId: string | null;
  /** Non-null only for subagent child events — the parent opencode session. */
  parentSessionId: string | null;
  /** On a parent `task` event, the child session it spawned; else null. */
  subagentSessionId: string | null;
}

export interface ParsedToolCallProgress {
  type: "tool_call_progress";
  toolCallId: string;
  toolName: ToolName;
  kind: import("../types/displayTypes").ToolCallKind;
  status: import("../types/displayTypes").ToolCallStatus;
  isTodo: boolean;
  // Pre-extracted, pre-sanitized fields (ready for display)
  title: string;
  description: string;
  command: string;
  rawOutput: string;
  filePath: string; // Session-relative
  subagentType: string | null;
  skillName: string | null;
  // Edit-specific
  isNewFile: boolean;
  oldContent: string;
  newContent: string;
  // Todo-specific
  todos: TodoItem[];
  // Task-specific
  taskOutput: string | null;
  /** Opencode session this event was emitted on — child's id for subagent child events, else null. */
  sessionId: string | null;
  /** Non-null only for subagent child events — the parent opencode session. */
  parentSessionId: string | null;
  /** On a parent `task` event, the child session it spawned; else null. */
  subagentSessionId: string | null;
}

export interface ParsedPromptResponse {
  type: "prompt_response";
}

export interface ParsedArtifact {
  type: "artifact_created";
  artifact: {
    id: string;
    type: string;
    name: string;
    path: string;
    preview_url: string | null;
  };
}

export interface ParsedError {
  type: "error";
  message: string;
}

export interface ParsedApprovalRequested {
  type: "approval_requested";
  approvalId: string;
  sessionId: string;
}

export interface ParsedSubagentStarted {
  type: "subagent_started";
  subagentSessionId: string;
  parentSessionId: string | null;
}

export interface ParsedUnknown {
  type: "unknown";
}

export type ParsedPacket =
  | ParsedTextChunk
  | ParsedThinkingChunk
  | ParsedToolCallStart
  | ParsedToolCallProgress
  | ParsedPromptResponse
  | ParsedArtifact
  | ParsedApprovalRequested
  | ParsedSubagentStarted
  | ParsedError
  | ParsedUnknown;
