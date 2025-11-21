// "AppFocus" is the current part of the main application which is active / focused on.
// Namely, if the URL is pointing towards a "chat", then a `{ type: "chat", id: "..." }` is returned.
//
// This is useful in determining what `SidebarTab` should be active, for example.

import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { usePathname, useSearchParams } from "next/navigation";

export type AppFocus =
  | { type: "agent" | "project" | "chat"; id: string }
  | "new-session"
  | "more-agents";

export default function useAppFocus(): AppFocus {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Check if we're on the agents page
  if (pathname === "/chat/agents") {
    return "more-agents";
  }

  // Check search params for chat, agent, or project
  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  if (chatId) return { type: "chat", id: chatId };

  const agentId = searchParams.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  if (agentId) return { type: "agent", id: agentId };

  const projectId = searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID);
  if (projectId) return { type: "project", id: projectId };

  // No search params means we're on a new session
  return "new-session";
}
