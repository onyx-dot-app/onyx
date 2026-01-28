/**
 * Stream Item Helpers
 *
 * Reduced to only utility functions that are NOT packet-processing concerns.
 * All packet parsing, tool detection, and path sanitization now live in parsePacket.ts.
 */

/**
 * Generate a unique ID for stream items
 */
export function genId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
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
