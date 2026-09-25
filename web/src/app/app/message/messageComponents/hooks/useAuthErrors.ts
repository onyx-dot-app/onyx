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

  for (const packet of rawPackets) {
    if (packet.obj.type !== PacketType.CUSTOM_TOOL_DELTA) {
      continue;
    }

    const delta = packet.obj as CustomToolDelta;
    if (!delta.error?.is_auth_error) {
      continue;
    }

    const alreadyPresent = errors.some(
      (error) =>
        (delta.tool_id != null && error.toolId === delta.tool_id) ||
        (delta.tool_id == null && error.toolName === delta.tool_name)
    );

    if (!alreadyPresent) {
      errors.push({
        toolName: delta.tool_name,
        toolId: delta.tool_id ?? null,
      });
    }
  }

  return errors;
}
