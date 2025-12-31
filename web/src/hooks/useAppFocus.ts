"use client";

// "AppFocus" is the current part of the main application which is active / focused on.
// Namely, if the URL is pointing towards a "chat", then a `{ type: "chat", id: "..." }` is returned.
//
// This is useful in determining what `SidebarTab` should be active, for example.

import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { usePathname, useSearchParams } from "next/navigation";

export type AppFocusType =
  | { type: "agent" | "project" | "chat"; id: string }
  | "new-session"
  | "more-agents"
  | "settings";

export class AppFocus {
  constructor(public value: AppFocusType) {}

  isAgent(): boolean {
    return typeof this.value === "object" && this.value.type === "agent";
  }

  isProject(): boolean {
    return typeof this.value === "object" && this.value.type === "project";
  }

  isChat(): boolean {
    return typeof this.value === "object" && this.value.type === "chat";
  }

  isNewSession(): boolean {
    return this.value === "new-session";
  }

  isMoreAgents(): boolean {
    return this.value === "more-agents";
  }

  isSettings(): boolean {
    return this.value === "settings";
  }

  getId(): string | null {
    return typeof this.value === "object" ? this.value.id : null;
  }

  getType():
    | "agent"
    | "project"
    | "chat"
    | "new-session"
    | "more-agents"
    | "settings" {
    return typeof this.value === "object" ? this.value.type : this.value;
  }
}

export default function useAppFocus(): AppFocus {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Check if we're on the settings page
  if (pathname.startsWith("/chat/settings")) {
    return new AppFocus("settings");
  }

  // Check if we're on the agents page
  if (pathname.startsWith("/chat/agents")) {
    return new AppFocus("more-agents");
  }

  // Check search params for chat, agent, or project
  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  if (chatId) return new AppFocus({ type: "chat", id: chatId });

  const agentId = searchParams.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  if (agentId) return new AppFocus({ type: "agent", id: agentId });

  const projectId = searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID);
  if (projectId) return new AppFocus({ type: "project", id: projectId });

  // No search params means we're on a new session
  return new AppFocus("new-session");
}
