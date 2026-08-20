"use client";

// "AppFocus" is the current part of the main application which is active / focused on.
// Namely, if the URL is pointing towards a "chat", then a `{ type: "chat", id: "..." }` is returned.
//
// This is useful in determining what `SidebarTab` should be active, for example.

import { useMemo } from "react";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { usePathname, useSearchParams } from "next/navigation";

export type AppFocusType =
  | { type: "agent" | "project" | "chat"; id: string }
  | "new-session"
  | "more-agents"
  | "user-settings"
  | "shared-chat";

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

  isSharedChat(): boolean {
    return this.value === "shared-chat";
  }

  isNewSession(): boolean {
    return this.value === "new-session";
  }

  isMoreAgents(): boolean {
    return this.value === "more-agents";
  }

  isUserSettings(): boolean {
    return this.value === "user-settings";
  }

  getId(): string | null {
    return typeof this.value === "object" ? this.value.id : null;
  }

  getType():
    | "agent"
    | "project"
    | "chat"
    | "shared-chat"
    | "new-session"
    | "more-agents"
    | "user-settings" {
    return typeof this.value === "object" ? this.value.type : this.value;
  }

  // # NOTE (@raunakab):
  // ## Composite questions
  //
  // Some call-sites ask the same question about several focus states at once.
  // Each helper below names that question. The state list then lives here
  // instead of being spelled out, and drifting, at each call-site.

  /**
   * True while the user reads a conversation, either their own or a shared one.
   *
   * `useAppDocumentTitle` uses this to decide when the chat name belongs in
   * the document title. `AppPage` uses it to decide when the sources panel may
   * stay open — there the shared arm changes nothing, because shared chats
   * render through `SharedChatDisplay`, which has no sources panel.
   */
  isChattable(): boolean {
    return this.isChat() || this.isSharedChat();
  }

  /**
   * True when the active agent's sidebar tab must look selected.
   *
   * The tab highlights in more cases than an explicit click on it. Two
   * examples:
   *
   * - You are in a chat that started with `Agent XYZ`. The chat tab *and* the
   *   `Agent XYZ` tab both highlight.
   * - "Disable Default Chat" is on (Admin -> Chat Preferences -> Advanced
   *   Options). You open "New Session" (`/app`), which resolves to an agent
   *   because no default chat exists. The new-session tab *and* that agent's
   *   tab both highlight.
   */
  isAgentTabHighlightable(): boolean {
    return (
      this.isAgent() ||
      this.isNewSession() ||
      this.isChat() ||
      this.isSharedChat()
    );
  }
}

export default function useAppFocus(): AppFocus {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const agentId = searchParams.get(SEARCH_PARAM_NAMES.AGENT_ID);
  const projectId = searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID);

  // Memoize on the values that determine which AppFocus is constructed.
  // AppFocus is immutable, so same inputs → same instance.
  return useMemo(() => {
    if (pathname.startsWith("/app/shared/")) {
      return new AppFocus("shared-chat");
    }
    if (pathname.startsWith("/app/settings")) {
      return new AppFocus("user-settings");
    }
    if (pathname.startsWith("/app/agents")) {
      return new AppFocus("more-agents");
    }
    if (chatId) return new AppFocus({ type: "chat", id: chatId });
    if (agentId) return new AppFocus({ type: "agent", id: agentId });
    if (projectId) return new AppFocus({ type: "project", id: projectId });
    return new AppFocus("new-session");
  }, [pathname, chatId, agentId, projectId]);
}
