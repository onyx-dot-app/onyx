import { AgentsPageLoader } from "@/lib/agents/components";

/**
 * Shown the moment the agents page is opened, while it renders: Next
 * prefetches this shell, so the switch from a sidebar tab is instant.
 */
export default function Loading() {
  return <AgentsPageLoader />;
}
