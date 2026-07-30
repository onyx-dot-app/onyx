/**
 * Subagent Routing
 *
 * Shared classification + mapping helpers for routing parsed tool-call packets
 * into the main transcript vs. a subagent's own tool-call list. Used by both
 * the live SSE path (useBuildStreaming) and the historical reconstruction path
 * (useBuildSessionStore.loadSession) so the two never drift.
 *
 * Routing semantics (from the backend `_meta`):
 * - Child (subagent-internal) event: parentSessionId != null AND sessionId != null.
 *   Belongs to the subagent identified by `sessionId` — NOT the main transcript.
 * - Parent `task` event: subagentSessionId != null. Stays in the main transcript
 *   (the task card) AND seeds/updates the subagent meta for `subagentSessionId`.
 * - Normal event: all three null → main transcript, unchanged.
 */

import type {
  ParsedToolCallProgress,
  ParsedToolCallStart,
} from "./packetTypes";
import type { ToolCallState } from "../types/displayTypes";

export type SubagentEventClass =
  | { kind: "child"; subagentSessionId: string }
  | { kind: "parentTask"; subagentSessionId: string }
  | { kind: "normal" };

/**
 * Classify a parsed tool-call progress packet for subagent routing.
 *
 * Child detection takes precedence: a packet with a non-null parentSessionId
 * (and its own sessionId) is always a subagent-internal event.
 */
export function classifySubagentEvent(
  parsed: ParsedToolCallProgress
): SubagentEventClass {
  if (parsed.parentSessionId !== null && parsed.sessionId !== null) {
    return { kind: "child", subagentSessionId: parsed.sessionId };
  }
  if (parsed.subagentSessionId !== null) {
    return { kind: "parentTask", subagentSessionId: parsed.subagentSessionId };
  }
  return { kind: "normal" };
}

/**
 * Build a ToolCallState from a parsed tool-call progress packet — the SAME
 * mapping used by the main transcript builder, so child tool calls render
 * identically wherever they appear.
 */
export function toolCallStateFromProgress(
  parsed: ParsedToolCallProgress
): ToolCallState {
  return {
    id: parsed.toolCallId,
    kind: parsed.kind,
    title: parsed.title,
    description: parsed.description,
    command: parsed.command,
    status: parsed.status,
    rawOutput: parsed.rawOutput,
    toolName: parsed.toolName,
    subagentType: parsed.subagentType ?? undefined,
    skillName: parsed.skillName ?? undefined,
    taskOutput: parsed.taskOutput ?? undefined,
    isNewFile: parsed.isNewFile,
    oldContent: parsed.oldContent,
    newContent: parsed.newContent,
  };
}

export function toolCallStateFromStart(
  parsed: ParsedToolCallStart
): ToolCallState {
  return {
    id: parsed.toolCallId,
    kind: parsed.kind,
    title: parsed.title,
    description: parsed.description,
    command: parsed.command,
    status: "pending",
    rawOutput: "",
    toolName: parsed.toolName,
    subagentType: parsed.subagentType ?? undefined,
    skillName: parsed.skillName ?? undefined,
    isNewFile: true,
    oldContent: "",
    newContent: "",
  };
}

/**
 * Clean a raw task-output string for display in the subagent panel.
 *
 * Raw output looks like:
 *   task_id: ses_xxx (for resuming to continue this task if needed)
 *
 *   <task_result>
 *   ...actual answer...
 *   </task_result>
 *
 * Strips a leading `task_id: ...` line and unwraps a single
 * `<task_result>...</task_result>` block if present. Returns the trimmed input
 * when neither pattern matches. Null/empty input → null.
 */
export function cleanTaskOutput(raw: string | null): string | null {
  if (!raw) return null;
  let text = raw.trim();
  if (!text) return null;

  // Strip a leading "task_id: ..." line.
  text = text.replace(/^task_id:[^\n]*\n?/, "").trim();

  // Unwrap a single <task_result>...</task_result> block.
  const match = text.match(/<task_result>([\s\S]*?)<\/task_result>/);
  if (match?.[1] !== undefined) {
    text = match[1].trim();
  }

  return text || null;
}

/** Derive a short subagent display name from a parsed parent `task` packet. */
export function subagentNameFromTask(parsed: ParsedToolCallProgress): string {
  const displayDescription = parsed.description
    .replace(/^Spawning subagent:\s*/, "")
    .trim();
  const firstLine =
    (displayDescription || parsed.command).split("\n")[0]?.trim() ?? "";
  if (firstLine) {
    return firstLine.length > 40 ? `${firstLine.slice(0, 40)}…` : firstLine;
  }
  return parsed.subagentType ?? "subagent";
}

export function subagentNameFromToolCall(toolCall: ToolCallState): string {
  const firstLine = (toolCall.command || toolCall.description || "")
    .replace(/^Spawning subagent:\s*/, "")
    .split("\n")[0]
    ?.trim();
  if (firstLine) {
    return firstLine.length > 40 ? `${firstLine.slice(0, 40)}…` : firstLine;
  }
  return toolCall.subagentType ?? "subagent";
}
