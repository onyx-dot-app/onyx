import type { ToolCallState } from "@/app/craft/types/displayTypes";

export function isSkillInvocation(toolCall: ToolCallState): boolean {
  return toolCall.toolName === "skill";
}

/** The invocation or a tool call made inside a skill (drives the comet edge). */
export function isSkillCall(toolCall: ToolCallState): boolean {
  return toolCall.toolName === "skill" || !!toolCall.skillName;
}

/**
 * Returns the language hint to use for syntax highlighting in the body.
 * Uses the file path's extension when present, falls back to the tool kind.
 */
export function getLanguageHint(toolCall: ToolCallState): string | undefined {
  if (toolCall.kind === "execute") return "bash";
  if (toolCall.kind === "read" || toolCall.kind === "edit") {
    return toolCall.description;
  }
  return undefined;
}
