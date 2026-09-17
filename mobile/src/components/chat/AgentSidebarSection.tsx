import { router, useGlobalSearchParams } from "expo-router";

import { useAgents, usePinnedAgents } from "@/api/chat/agents";
import { useChatSessions } from "@/api/chat/sessions";
import { AgentAvatar } from "@/components/avatars/AgentAvatar";
import { SidebarLayouts, SidebarTab, useSidebar } from "@/components/sidebar";
import { buildAgentRail, MinimalAgent } from "@/chat/agents";
import { useSelectAgent } from "@/hooks/useLiveAgent";
import SvgOnyxOctagon from "@/icons/onyx-octagon";

// Sidebar "Agents" rail: pinned agents + the active agent, then a gallery link. Tap = new chat.
export function AgentSidebarSection() {
  const { setFolded } = useSidebar();
  const { agents } = useAgents();
  const { pinnedAgents } = usePinnedAgents();
  const { sessions } = useChatSessions();
  const selectAgent = useSelectAgent();
  const params = useGlobalSearchParams<{ id?: string; agentId?: string }>();

  if (agents.length === 0) return null;

  // Active agent: the open session's persona, else the landing's selected agent param.
  const currentSessionId = typeof params.id === "string" ? params.id : null;
  const sessionPersonaId = currentSessionId
    ? (sessions.find((s) => s.id === currentSessionId)?.persona_id ?? null)
    : null;
  const paramAgentId =
    typeof params.agentId === "string" ? Number(params.agentId) : NaN;
  const currentAgentId =
    sessionPersonaId ?? (Number.isNaN(paramAgentId) ? null : paramAgentId);

  const rail = buildAgentRail(pinnedAgents, agents, currentAgentId);

  function pick(agent: MinimalAgent) {
    selectAgent(agent, () => setFolded(true));
  }

  function openGallery() {
    setFolded(true);
    router.navigate("/agents");
  }

  return (
    <SidebarLayouts.Section title="Agents">
      {rail.map((agent) => (
        <SidebarTab
          key={agent.id}
          leading={<AgentAvatar agent={agent} size={16} />}
          selected={agent.id === currentAgentId}
          onPress={() => pick(agent)}
        >
          {agent.name}
        </SidebarTab>
      ))}
      <SidebarTab icon={SvgOnyxOctagon} onPress={openGallery}>
        {rail.length === 0 ? "Explore agents" : "More agents"}
      </SidebarTab>
    </SidebarLayouts.Section>
  );
}
