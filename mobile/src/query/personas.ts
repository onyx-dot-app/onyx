// Personas (agents) query. GET /api/persona returns the list of personas/agents.
import type { MinimalAgent } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export function usePersonas() {
  return useSimpleQuery<MinimalAgent[]>(queryKeys.personas);
}

/**
 * Resolve the active agent for a chat. Prefers the session's persona, but falls
 * back to the default assistant when the session has none yet (e.g. a brand-new
 * draft chat where `personaId` is undefined). The default matches
 * useChatSessionLifecycle's new-chat default: persona id 0, else the first.
 * Returns undefined only when personas haven't loaded.
 */
export function resolveAgent(
  personas: MinimalAgent[] | undefined,
  personaId: number | undefined
): MinimalAgent | undefined {
  if (!personas || personas.length === 0) return undefined;
  return (
    personas.find((p) => p.id === personaId) ??
    personas.find((p) => p.id === 0) ??
    personas[0]
  );
}
