import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";

// The endpoint actually returns full ToolSnapshot objects; this only types the field callers
// need — the id, to test membership.
interface AvailableTool {
  id: number;
}

const EMPTY_TOOLS: AvailableTool[] = [];

// `GET /tool` returns only tools that currently pass their backend `is_available()` check — e.g.
// image generation is omitted if no provider is configured. That's a different, narrower list
// than an agent's assigned `tools`, which is what it's configured to use whether or not that's
// actually live right now.
export function useAvailableTools() {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.availableTools(serverUrl),
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => apiFetch<AvailableTool[]>("/tool", { signal }),
    refetchInterval: 60_000,
  });

  // A malformed response is treated as not-yet-loaded rather than "confirmed zero tools
  // available", which would otherwise mark every tool the agent has assigned as unavailable.
  const tools = Array.isArray(query.data) ? query.data : EMPTY_TOOLS;
  return {
    ...query,
    isSuccess: query.isSuccess && Array.isArray(query.data),
    tools,
  };
}
