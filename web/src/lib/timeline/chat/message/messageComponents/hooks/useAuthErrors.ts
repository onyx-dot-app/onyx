import { useMemo } from "react";
import {
  CustomToolDelta,
  CustomToolStart,
  Packet,
  PacketType,
  Placement,
} from "@/app/app/services/streamingModels";

export interface AuthError {
  turnIndex: number;
  toolName: string;
  toolId: number | null;
  /** The integration of an app tool, which has no tool ID. */
  integrationId: number | null;
}

export function useAuthErrors(rawPackets: Packet[]): AuthError[] {
  // Streams append to the same array, so its length keys the result too.
  const packetCount = rawPackets.length;
  return useMemo(
    () => computeAuthErrors(rawPackets.slice(0, packetCount)),
    [rawPackets, packetCount]
  );
}

// A tool call's start and delta packets share one placement.
function callKey(placement: Placement): string {
  return `${placement.turn_index}-${placement.tab_index ?? 0}-${
    placement.sub_turn_index ?? ""
  }`;
}

function computeAuthErrors(rawPackets: Packet[]): AuthError[] {
  const labels = new Map<string, string>();
  const errors: AuthError[] = [];
  // Labels can repeat across tools, so deduplicate on the tool ID or the
  // qualified tool name within each section.
  const seen = new Set<string>();

  for (const packet of rawPackets) {
    if (packet.obj.type === PacketType.CUSTOM_TOOL_START) {
      labels.set(
        callKey(packet.placement),
        (packet.obj as CustomToolStart).display_name
      );
      continue;
    }
    // Each accepted user message starts a section with its own auth cards.
    if (packet.obj.type === PacketType.USER_MESSAGE) {
      seen.clear();
      continue;
    }
    if (packet.obj.type !== PacketType.CUSTOM_TOOL_DELTA) {
      continue;
    }

    const delta = packet.obj as CustomToolDelta;
    if (!delta.error?.is_auth_error) {
      continue;
    }

    // One card for each integration: an app has a tool for each action.
    const key =
      delta.tool_id != null
        ? `id:${delta.tool_id}`
        : delta.integration_id != null
          ? `integration:${delta.integration_id}`
          : `name:${delta.tool_name}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    errors.push({
      turnIndex: packet.placement.turn_index,
      toolName: labels.get(callKey(packet.placement)) ?? delta.tool_name,
      toolId: delta.tool_id ?? null,
      integrationId: delta.integration_id ?? null,
    });
  }

  return errors;
}
