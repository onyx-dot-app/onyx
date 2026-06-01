// Personas (agents) query. GET /api/persona returns the list of personas/agents.
import type { MinimalAgent } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export function usePersonas() {
  return useSimpleQuery<MinimalAgent[]>(queryKeys.personas);
}

// Active agent for a chat: the session's persona, else the default assistant
// (id 0, else the first) — matching useChatSessionLifecycle's new-chat default.
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
