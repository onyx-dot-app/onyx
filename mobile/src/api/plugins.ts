import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { useSession } from "@/state/session";

/*
 * The plugins a chat of the agent runs for the user, as the server decides them: the same list web's
 * `useAgentPluginIds` reads. `GET /tool` lists no MCP plugins, so an allow-list built from it would
 * turn MCP-only plugins off. Null until it loads and on a failed read.
 */
export function useAgentPluginIds(agentId: number | null): string[] | null {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.agentPluginIds(serverUrl, agentId),
    enabled: serverUrl !== null && agentId !== null,
    queryFn: ({ signal }) =>
      apiFetch<string[]>(`/plugins/agents/${agentId ?? 0}`, { signal }),
  });
  return query.isSuccess ? query.data : null;
}
