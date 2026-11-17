import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import { DEFAULT_AGENT_ID } from "@/chat/agents";
import { useSession } from "@/state/session";

interface MemberPluginRef {
  plugin_id: string;
  enabled: boolean;
}

interface MemberIntegration {
  plugins: MemberPluginRef[];
}

interface AgentDetail {
  plugins?: { plugin_id: string }[] | null;
}

async function fetchAgentPluginIds(
  agentId: number,
  signal: AbortSignal,
): Promise<string[]> {
  if (agentId === DEFAULT_AGENT_ID) {
    // The default agent runs each plugin with integrations that the user turned on.
    const integrations = await apiFetch<MemberIntegration[]>("/integrations", {
      signal,
    });
    return [
      ...new Set(
        integrations.flatMap((integration) =>
          integration.plugins
            .filter((ref) => ref.enabled)
            .map((ref) => ref.plugin_id),
        ),
      ),
    ];
  }
  const detail = await apiFetch<AgentDetail>(`/persona/${agentId}`, { signal });
  return [...new Set((detail.plugins ?? []).map((link) => link.plugin_id))];
}

/*
 * Every plugin of an agent, the same list web's `useAgentChatPlugins` reads. `GET /tool` lists no
 * MCP plugins, so an allow-list built from it would turn MCP-only plugins off. Null until it loads
 * and on a failed read.
 */
export function useAgentPluginIds(agentId: number | null): string[] | null {
  const serverUrl = useSession((state) => state.serverUrl);
  const query = useQuery({
    queryKey: QUERY_KEYS.agentPluginIds(serverUrl, agentId),
    enabled: serverUrl !== null && agentId !== null,
    queryFn: ({ signal }) => fetchAgentPluginIds(agentId ?? 0, signal),
  });
  return query.isSuccess ? query.data : null;
}
