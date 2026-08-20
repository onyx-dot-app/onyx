"use client";

import { useLayoutEffect } from "react";
import { usePathname } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";
import useAppFocus from "@/hooks/useAppFocus";
import useChatSessions from "@/hooks/useChatSessions";
import { useActiveAgent, useAgents } from "@/lib/agents/hooks";
import {
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/app/app/components/tools/constants";

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
 * Before a session exists, the active agent is the one about to answer.
 */
export function useChatSessionSupportsRetrieval(): boolean {
  const { agents } = useAgents();
  const { currentChatSession } = useChatSessions();
  const activeAgent = useActiveAgent();

  const agent = currentChatSession
    ? agents.find((candidate) => candidate.id === currentChatSession.persona_id)
    : activeAgent;

  return (agent?.tools ?? []).some(
    (tool) =>
      tool.in_code_tool_id &&
      [SEARCH_TOOL_ID, WEB_SEARCH_TOOL_ID].includes(tool.in_code_tool_id)
  );
}
