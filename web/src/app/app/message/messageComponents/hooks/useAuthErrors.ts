import { useRef } from "react";
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
  const stateRef = useRef<{ processedCount: number; errors: AuthError[] }>({
    processedCount: 0,
    errors: [],
  });

  // Reset if packets shrunk (e.g. new message)
  if (rawPackets.length < stateRef.current.processedCount) {
    stateRef.current = { processedCount: 0, errors: [] };
  }

  // Process only new packets (incremental, like usePacketProcessor)
  if (rawPackets.length > stateRef.current.processedCount) {
    let newErrors = stateRef.current.errors;
    for (let i = stateRef.current.processedCount; i < rawPackets.length; i++) {
      const packet = rawPackets[i]!;
      if (packet.obj.type === PacketType.CUSTOM_TOOL_DELTA) {
        const delta = packet.obj as CustomToolDelta;
        if (delta.error?.is_auth_error) {
          const alreadyPresent = newErrors.some(
            (e) =>
              (delta.tool_id != null && e.toolId === delta.tool_id) ||
              (delta.tool_id == null && e.toolName === delta.tool_name)
          );
          if (!alreadyPresent) {
            newErrors = [
              ...newErrors,
              { toolName: delta.tool_name, toolId: delta.tool_id ?? null },
            ];
          }
        }
      }
    }
    stateRef.current = {
      processedCount: rawPackets.length,
      errors: newErrors,
    };
  }

  return stateRef.current.errors;
}
