"use client";

// "AppPosition" is where in the main application the user currently is. It is
// derived from the URL and nothing else, so any flow that needs to put the user
// somewhere — or to know where they are — states it as a URL and reads it back
// here, rather than keeping a second copy of the answer in component state.

import { useMemo } from "react";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { usePathname, useSearchParams } from "next/navigation";

export type AppPositionType =
  | { location: "agent" | "project" | "chat"; id: string }
  // The agents listing, holding the agent whose viewer is open over it, if any.
  | { location: "more-agents"; id: string | null }
  | { location: "new-session" | "user-settings" | "shared-chat" };

export class AppPosition {
  constructor(public value: AppPositionType) {}

  /**
   * The id of whatever this position names, or null.
   *
   * One accessor per location rather than a predicate plus an untyped `getId`.
   * The pair made every caller ask two questions to get one answer, and nothing
   * stopped it asking the second without the first — reading a chat id while
   * standing in a project type-checked fine.
   */
  agent(): string | null {
    return this.value.location === "agent" ? this.value.id : null;
  }

  project(): string | null {
    return this.value.location === "project" ? this.value.id : null;
  }

  chat(): string | null {
    return this.value.location === "chat" ? this.value.id : null;
  }

  /** The agent whose viewer modal is open, if one is. */
  previewedAgent(): string | null {
    return this.value.location === "more-agents" ? this.value.id : null;
  }

  isAgent(): boolean {
    return this.agent() !== null;
  }

  isProject(): boolean {
    return this.project() !== null;
  }

  isChat(): boolean {
    return this.chat() !== null;
  }

  isSharedChat(): boolean {
    return this.value.location === "shared-chat";
  }

  isNewSession(): boolean {
    return this.value.location === "new-session";
  }

  /**
   * True on the agents listing, including while an agent's viewer is open over
   * it. The modal is a position in its own right so it can be linked to and
   * dismissed with the back button, but it is still that page underneath.
   */
  isMoreAgents(): boolean {
    return this.value.location === "more-agents";
  }

  isUserSettings(): boolean {
    return this.value.location === "user-settings";
  }

  // # NOTE (@raunakab):
  // ## Composite questions
  //
  // Some call-sites ask the same question about several positions at once.
  // Each helper below names that question. The list then lives here instead of
  // being spelled out, and drifting, at each call-site.

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

export default function useAppPosition(): AppPosition {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const agentId = searchParams.get(SEARCH_PARAM_NAMES.AGENT_ID);
  const projectId = searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID);

  // Memoize on the values that determine which AppPosition is constructed.
  // AppPosition is immutable, so same inputs → same instance.
  return useMemo(() => {
    if (pathname.startsWith("/app/shared/")) {
      return new AppPosition({ location: "shared-chat" });
    }
    if (pathname.startsWith("/app/settings")) {
      return new AppPosition({ location: "user-settings" });
    }
    // On the listing, an agent id names the viewer that is open rather than a
    // chat to start, which is why the same parameter reads differently here.
    if (pathname.startsWith("/app/agents")) {
      return new AppPosition({ location: "more-agents", id: agentId });
    }
    if (chatId) return new AppPosition({ location: "chat", id: chatId });
    if (agentId) return new AppPosition({ location: "agent", id: agentId });
    if (projectId) {
      return new AppPosition({ location: "project", id: projectId });
    }
    return new AppPosition({ location: "new-session" });
  }, [pathname, chatId, agentId, projectId]);
}
