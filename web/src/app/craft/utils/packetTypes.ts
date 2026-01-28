/**
 * Packet Types
 *
 * Type definitions for raw and parsed ACP packets.
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
  | "unknown";

export interface ParsedTextChunk {
  type: "text_chunk";
  text: string;
}

export interface ParsedThinkingChunk {
  type: "thinking_chunk";
  text: string;
}

export interface ParsedToolCallStart {
  type: "tool_call_start";
  toolCallId: string;
  toolName: ToolName;
  kind: import("../types/displayTypes").ToolCallKind;
  isTodo: boolean;
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
  // Edit-specific
  isNewFile: boolean;
  oldContent: string;
  newContent: string;
  // Todo-specific
  todos: TodoItem[];
  // Task-specific
  taskOutput: string | null;
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
  | ParsedError
  | ParsedUnknown;
