export const DEFAULT_AGENT_ID = 0;

// Backend StarterMessage is exactly {name, message} — no description.
export interface AgentStarterMessage {
  name: string;
  message: string;
}

export interface AgentLabel {
  id: number;
  name: string;
}

// Selection subset of MinimalPersonaSnapshot; rich fields added when a slice needs them.
export interface MinimalAgent {
  id: number;
  name: string;
  description: string;
  starter_messages: AgentStarterMessage[] | null;
  uploaded_image_id: string | null;
  icon_name: string | null;
  is_public: boolean;
  is_listed: boolean;
  is_featured: boolean;
  builtin_persona: boolean;
  display_priority: number | null;
  labels: AgentLabel[];
}

// Explicit `pinned_assistants` (in order, unknown ids dropped), or — when null/undefined —
// featured agents excluding id 0. An empty array stays empty (no fallback).
export function resolvePinnedAgents(
  agents: MinimalAgent[],
  pinnedIds: number[] | null | undefined,
): MinimalAgent[] {
  if (agents.length === 0) return [];
  if (pinnedIds == null) {
    return agents.filter((a) => a.is_featured && a.id !== DEFAULT_AGENT_ID);
  }
  return pinnedIds
    .map((id) => agents.find((a) => a.id === id))
    .filter((a): a is MinimalAgent => a != null);
}

export interface LiveAgentInputs {
  agents: MinimalAgent[];
  pinnedAgents: MinimalAgent[];
  disableDefaultAssistant: boolean;
  selectedAgentId: number | null;
  sessionPersonaId: number | null;
}

// Precedence: existing session's persona → explicit selection → default (id 0 when enabled,
// else first pinned/available).
export function resolveLiveAgent({
  agents,
  pinnedAgents,
  disableDefaultAssistant,
  selectedAgentId,
  sessionPersonaId,
}: LiveAgentInputs): MinimalAgent | null {
  if (agents.length === 0) return null;

  if (sessionPersonaId != null) {
    return agents.find((a) => a.id === sessionPersonaId) ?? null;
  }

  if (selectedAgentId != null) {
    const selected = agents.find((a) => a.id === selectedAgentId);
    // Ignore an explicit default-agent (id 0) selection when the workspace disables it.
    if (
      selected &&
      !(disableDefaultAssistant && selected.id === DEFAULT_AGENT_ID)
    ) {
      return selected;
    }
  }

  if (disableDefaultAssistant) {
    const nonDefaultPinned = pinnedAgents.filter(
      (a) => a.id !== DEFAULT_AGENT_ID,
    );
    const nonDefaultAvailable = agents.filter((a) => a.id !== DEFAULT_AGENT_ID);
    return nonDefaultPinned[0] ?? nonDefaultAvailable[0] ?? agents[0] ?? null;
  }

  const unified = agents.find((a) => a.id === DEFAULT_AGENT_ID);
  if (unified) return unified;
  return pinnedAgents[0] ?? agents[0] ?? null;
}

export function agentMatchesSearch(
  agent: MinimalAgent,
  query: string,
): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  if (agent.name.toLowerCase().includes(needle)) return true;
  return agent.labels.some((l) => l.name.toLowerCase().includes(needle));
}

// Drops builtins, splits into featured/all sections, each sorted by descending id.
export function splitAgentsForGallery(
  agents: MinimalAgent[],
  query: string,
): { featured: MinimalAgent[]; all: MinimalAgent[] } {
  const byIdDesc = (a: MinimalAgent, b: MinimalAgent) => b.id - a.id;
  const visible = agents
    .filter((a) => !a.builtin_persona)
    .filter((a) => agentMatchesSearch(a, query));
  return {
    featured: visible.filter((a) => a.is_featured).sort(byIdDesc),
    all: visible.filter((a) => !a.is_featured).sort(byIdDesc),
  };
}

// Pinned agents minus id 0, plus the active agent when it isn't already pinned (so the open
// chat's agent stays visible/highlightable).
export function buildAgentRail(
  pinnedAgents: MinimalAgent[],
  allAgents: MinimalAgent[],
  currentAgentId: number | null,
): MinimalAgent[] {
  const rail = pinnedAgents.filter((a) => a.id !== DEFAULT_AGENT_ID);
  if (
    currentAgentId != null &&
    currentAgentId !== DEFAULT_AGENT_ID &&
    !rail.some((a) => a.id === currentAgentId)
  ) {
    const current = allAgents.find((a) => a.id === currentAgentId);
    if (current) return [...rail, current];
  }
  return rail;
}
