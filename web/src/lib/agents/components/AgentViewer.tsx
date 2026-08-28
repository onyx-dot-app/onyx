"use client";

import { useEffect } from "react";
import { useAgent } from "@/lib/agents/hooks";
import { AgentViewerModal } from "@/lib/agents/components";
import { useAppPosition } from "@/lib/app/hooks";

/**
 * The agent viewer, opened by the URL rather than by whichever card was
 * clicked.
 *
 * One instance for the whole listing, because only something holding the
 * position and the agent together can tell that the two disagree. A card
 * cannot: it knows about one agent, so an id naming no agent at all matches
 * nothing and leaves the parameter sitting in the URL with nothing open.
 */
export function AgentViewer() {
  const appPosition = useAppPosition();

  const previewed = appPosition.previewedAgent();
  const agentId = previewed === null ? null : Number(previewed);
  const isRequestable = agentId !== null && Number.isInteger(agentId);

  const { agent, isLoading, error } = useAgent(isRequestable ? agentId : null);

  // An id naming nothing the user can open is not a position, so it does not
  // stay in the URL. Replaced rather than pushed: going back should reach
  // wherever the user came from, not the address that named nothing.
  const isUnopenable = previewed !== null && (!isRequestable || Boolean(error));
  useEffect(() => {
    if (isUnopenable) appPosition.openMoreAgents({ replace: true });
  }, [isUnopenable, appPosition]);

  // Nothing is rendered while the agent loads. The listing stays interactive
  // underneath, and a modal appearing late reads better than an empty one.
  if (previewed === null || isLoading || agent === null) return null;

  return (
    <AgentViewerModal
      agent={agent}
      onClose={() => appPosition.openMoreAgents()}
    />
  );
}
