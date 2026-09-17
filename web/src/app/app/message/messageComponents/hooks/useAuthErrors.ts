import { useMemo } from "react";
import { ResponseItem } from "@/app/app/services/streamingModels";
import { GroupedItem } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

interface AuthError {
  toolName: string;
  toolId: number | null;
}

export function useAuthErrors(toolGroups: readonly GroupedItem[]): AuthError[] {
  return useMemo(
    () => computeAuthErrors(toolGroups.flatMap((group) => group.items)),
    [toolGroups]
  );
}

function computeAuthErrors(items: readonly ResponseItem[]): AuthError[] {
  const errors: AuthError[] = [];

  for (const item of items) {
    const tool = item.content;
    if (
      tool.kind !== "tool" ||
      tool.metadata?.type !== "custom_tool_result" ||
      !tool.metadata.error?.is_auth_error
    )
      continue;
    if (
      errors.some((error) =>
        tool.tool_id != null
          ? error.toolId === tool.tool_id
          : error.toolName === tool.name
      )
    )
      continue;
    errors.push({ toolName: tool.name, toolId: tool.tool_id ?? null });
  }

  return errors;
}
