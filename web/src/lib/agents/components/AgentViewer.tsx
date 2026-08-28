"use client";

import { useAgent } from "@/lib/agents/hooks";
import { AgentViewerModal } from "@/lib/agents/components";

export interface AgentViewerProps {
  /** The agent being viewed, or null when nothing is. */
  agentId: number | null;
  onClose: () => void;
}

/**
 * The agent viewer, rendered once for the listing rather than once per card.
 *
 * A card knows about one agent, so cards that rendered their own viewer would
 * mount as many as there are agents in order to show one. Here the listing
 * says which agent is being viewed, and this fetches the full record that a
 * card's summary does not carry.
 */
export function AgentViewer({ agentId, onClose }: AgentViewerProps) {
  const { agent, isLoading } = useAgent(agentId);

  // Nothing is rendered while the agent loads. The listing stays interactive
  // underneath, and a modal appearing late reads better than an empty one.
  if (agentId === null || isLoading || agent === null) return null;

  return <AgentViewerModal agent={agent} onClose={onClose} />;
}
