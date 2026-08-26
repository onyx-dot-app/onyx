"use client";

import { useLayoutEffect } from "react";
import { usePathname } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";
import useAppFocus from "@/hooks/useAppFocus";
import useChatSessions from "@/hooks/useChatSessions";
import { useCurrentSessionPersonaId } from "@/app/app/stores/useChatSessionStore";
import { useActiveAgent, useAgents } from "@/lib/agents/hooks";
import { SEARCH_TOOL_ID, WEB_SEARCH_TOOL_ID } from "@/lib/tools/constants";

export function useCustomFooterContent(): string {
  const settings = useSettings();
  return (
    settings.enterprise?.custom_lower_disclaimer_content ||
    `[Onyx ${settings.version ?? "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}

export function useAppDocumentTitle(): void {
  const appFocus = useAppFocus();
  const { appName } = useSettings();
  const { currentChatSession } = useChatSessions();
  useLayoutEffect(() => {
    const appendChatNameToDocumentTitle =
      appFocus.isChattable() && currentChatSession?.name;
    document.title = appendChatNameToDocumentTitle
      ? `${currentChatSession.name} — ${appName}`
      : appName;
  }, [currentChatSession?.name, appName, appFocus]);
}

export function useAdminDocumentTitle(): void {
  const pathname = usePathname();
  const { appName } = useSettings();
  useLayoutEffect(() => {
    document.title = `Admin — ${appName}`;
  }, [pathname, appName]);
}

/**
 * True when the agent answering in this session can cite sources, through
 * internal search or web search.
 *
 * Inside a session the answer comes from that session's own agent, with no
 * fallback. A deleted or inaccessible agent resolves to nothing and reads as
 * false, so the sources panel goes away instead of describing a different
 * agent. {@link useActiveAgent} cannot be used here because it falls through
 * to the Assistant, then to pins, when the session's agent does not resolve.
 *
 * The id comes from the store, not from {@link useChatSessions}: that hook
 * pages 50 sessions at a time, so an older chat is absent from its list and
 * would read as "no session at all".
 *
 * Before a session exists, the active agent is the one about to answer.
 *
 * Returns null while the agent list loads. An empty list means "not known
 * yet", never "cannot retrieve", and a caller that acts on the difference
 * must wait rather than read a premature false.
 */
export function useChatSessionSupportsRetrieval(): boolean | null {
  const { agents, isLoading: isLoadingAgents } = useAgents();
  const sessionPersonaId = useCurrentSessionPersonaId();
  const activeAgent = useActiveAgent();

  // A failed fetch also leaves the list empty, with the loading flag already
  // down. Both cases read as "not known yet", so neither reports a false.
  if (isLoadingAgents || agents.length === 0) return null;

  const agent =
    sessionPersonaId === null
      ? activeAgent
      : agents.find((candidate) => candidate.id === sessionPersonaId);

  return (agent?.tools ?? []).some(
    (tool) =>
      tool.in_code_tool_id &&
      [SEARCH_TOOL_ID, WEB_SEARCH_TOOL_ID].includes(tool.in_code_tool_id)
  );
}
