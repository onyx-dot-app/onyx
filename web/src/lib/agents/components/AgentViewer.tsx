"use client";

import { useEffect } from "react";
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
  const { agent, isLoading, error } = useAgent(agentId);

  // An agent that cannot be read cannot be shown, and rendering nothing would
  // leave the listing looking like the click missed. Closing puts the user back
  // somewhere they can act, and clicking again retries.
  const failed = Boolean(error);
  useEffect(() => {
    if (failed) onClose();
  }, [failed, onClose]);

  // Nothing is rendered while the agent loads. The listing stays interactive
  // underneath, and a modal appearing late reads better than an empty one.
  if (agentId === null || isLoading || agent === null) return null;

  return <AgentViewerModal agent={agent} onClose={onClose} />;
}
