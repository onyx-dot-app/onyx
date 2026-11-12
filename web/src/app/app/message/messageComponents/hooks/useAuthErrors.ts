import { useMemo } from "react";
import {
  CustomToolDelta,
  Packet,
  PacketType,
} from "@/app/app/services/streamingModels";

interface AuthError {
  toolName: string;
  toolId: number | null;
}

export function useAuthErrors(rawPackets: Packet[]): AuthError[] {
  // Keyed on the packet array so re-renders between packet batches reuse
  // the same result identity instead of rescanning.
  return useMemo(() => computeAuthErrors(rawPackets), [rawPackets]);
}

function computeAuthErrors(rawPackets: Packet[]): AuthError[] {
  const errors: AuthError[] = [];
  // Labels can repeat across tools, so deduplicate on the tool ID or the
  // qualified tool name.
  const seen = new Set<string>();

  for (const packet of rawPackets) {
    if (packet.obj.type !== PacketType.CUSTOM_TOOL_DELTA) {
      continue;
    }

    const delta = packet.obj as CustomToolDelta;
    if (!delta.error?.is_auth_error) {
      continue;
    }

    const key =
      delta.tool_id != null ? `id:${delta.tool_id}` : `name:${delta.tool_name}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    errors.push({
      toolName: delta.display_name,
      toolId: delta.tool_id ?? null,
    });
  }

  return errors;
}
