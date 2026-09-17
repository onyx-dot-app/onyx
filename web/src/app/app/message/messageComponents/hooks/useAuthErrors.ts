import { useMemo } from "react";
import { Packet } from "@/app/app/services/streamingModels";
import { responseItems } from "@/app/app/services/packetUtils";

interface AuthError {
  toolName: string;
  toolId: number | null;
}

export function useAuthErrors(rawPackets: Packet[]): AuthError[] {
  // Keyed on the packet array so re-renders between packet batches reuse
  // the same result identity instead of rescanning.
  return useMemo(
    () => computeAuthErrors(rawPackets),
    [rawPackets, rawPackets.length]
  );
}

function computeAuthErrors(rawPackets: Packet[]): AuthError[] {
  const errors: AuthError[] = [];

  for (const item of responseItems(rawPackets)) {
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
