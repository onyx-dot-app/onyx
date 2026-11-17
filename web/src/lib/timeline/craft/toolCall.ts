import type { ToolCallState } from "@/app/craft/types/displayTypes";
import { parsePacket } from "@/app/craft/utils/parsePacket";
import { toolCallStateFromProgress } from "@/app/craft/utils/subagentRouting";
import type { AcpToolCall } from "@/lib/timeline/reducer";

/**
 * The display fields Craft's tool cards read, derived from an ACP tool call.
 *
 * The call goes through the same parsing the stream uses today, so titles,
 * descriptions, sanitized paths, diffs, skill names and task output match the
 * current cards exactly.
 */
export function toCraftToolCall(toolCall: AcpToolCall): ToolCallState {
  const parsed = parsePacket({
    type: "tool_call_progress",
    sessionUpdate: "tool_call_update",
    toolCallId: toolCall.toolCallId,
    title: toolCall.title,
    kind: toolCall.kind,
    status: toolCall.status,
    content: toolCall.content,
    locations: toolCall.locations,
    rawInput: toolCall.rawInput,
    rawOutput: toolCall.rawOutput,
    _meta: toolCall._meta,
  });

  if (parsed.type !== "tool_call_progress") {
    throw new Error("Expected a tool_call_progress packet");
  }
  const state: ToolCallState = toolCallStateFromProgress(parsed);

  const onyx = toolCall._meta?.onyx;
  return {
    ...state,
    // ACP has no cancelled status; Onyx carries it in `_meta.onyx`. A call
    // that completes after a Stop request completed.
    ...(onyx?.cancelled &&
      toolCall.status !== "completed" && { status: "cancelled" }),
    ...(onyx?.search && { onyxSearch: onyx.search }),
    ...(onyx?.exitCode !== undefined && { exitCode: onyx.exitCode }),
  };
}
