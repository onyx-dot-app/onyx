"use client";

import { useLayoutEffect, useMemo } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { routeWithQuery } from "@/lib/routes";
import { useSettings } from "@/lib/settings/hooks";
import { APP_SLOGAN } from "@/lib/constants";
import useChatSessions from "@/hooks/useChatSessions";
import { useCurrentSessionPersonaId } from "@/app/app/stores/useChatSessionStore";
import { useActiveAgent, useAgents } from "@/lib/agents/hooks";
import { SEARCH_TOOL_ID, WEB_SEARCH_TOOL_ID } from "@/lib/tools/constants";

// "AppPosition" is where in the main application the user currently is. It is
// derived from the URL and nothing else, so any flow that needs to put the user
// somewhere — or to know where they are — states it as a URL and reads it back
// here, rather than keeping a second copy of the answer in component state.

export type AppPositionType =
  | { location: "agent" | "project" | "chat"; id: string }
  // The agents listing, holding the agent whose viewer is open over it, if any.
  | { location: "more-agents"; id: string | null }
  | { location: "new-session" | "user-settings" | "shared-chat" };

export class AppPosition {
  constructor(public value: AppPositionType) {}

  static chat(id: string): AppPosition {
    return new AppPosition({ location: "chat", id });
  }

  static agent(id: number): AppPosition {
    return new AppPosition({ location: "agent", id: String(id) });
  }

  static project(id: number): AppPosition {
    return new AppPosition({ location: "project", id: String(id) });
  }

  /** The agents listing, with one agent's viewer open over it. */
  static agentViewer(id: number): AppPosition {
    return new AppPosition({ location: "more-agents", id: String(id) });
  }

  /** The agents listing with nothing open. */
  static moreAgents(): AppPosition {
    return new AppPosition({ location: "more-agents", id: null });
  }

  static newSession(): AppPosition {
    return new AppPosition({ location: "new-session" });
  }

  /**
   * Where to navigate to reach this position.
   *
   * The mirror of the derivation below: one class owns which pathname and
   * which parameter name each location lives at, so a caller names a position
   * and never assembles a URL. Reading and writing cannot drift apart, because
   * they are the same knowledge stated once in each direction.
   */
  href(): Route {
    switch (this.value.location) {
      case "chat":
        return routeWithQuery("/app", {
          [SEARCH_PARAM_NAMES.CHAT_ID]: this.value.id,
        });
      case "agent":
        return routeWithQuery("/app", {
          [SEARCH_PARAM_NAMES.AGENT_ID]: this.value.id,
        });
      case "project":
        return routeWithQuery("/app", {
          [SEARCH_PARAM_NAMES.PROJECT_ID]: this.value.id,
        });
      case "more-agents":
        return this.value.id === null
          ? ("/app/agents" as Route)
          : routeWithQuery("/app/agents", {
              [SEARCH_PARAM_NAMES.AGENT_ID]: this.value.id,
            });
      case "user-settings":
        return "/app/settings" as Route;
      case "shared-chat":
      case "new-session":
        return "/app" as Route;
    }
  }

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

export function useAppPosition(): AppPosition {
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

export function useCustomFooterContent(): string {
  const settings = useSettings();
  return (
    settings.enterprise?.custom_lower_disclaimer_content ||
    `[Onyx ${settings.version ?? "dev"}](https://www.onyx.app/) - ${APP_SLOGAN}`
  );
}

export function useAppDocumentTitle(): void {
  const appPosition = useAppPosition();
  const { appName } = useSettings();
  const { currentChatSession } = useChatSessions();
  useLayoutEffect(() => {
    const appendChatNameToDocumentTitle =
      appPosition.isChattable() && currentChatSession?.name;
    document.title = appendChatNameToDocumentTitle
      ? `${currentChatSession.name} — ${appName}`
      : appName;
  }, [currentChatSession?.name, appName, appPosition]);
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
