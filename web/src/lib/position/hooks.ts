"use client";

import { useMemo } from "react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { routeWithQuery } from "@/lib/routes";

// "AppPosition" is where in the main application the user currently is. It is
// derived from the URL and nothing else, so any flow that needs to put the user
// somewhere — or to know where they are — states it as a URL and reads it back
// here, rather than keeping a second copy of the answer in component state.

type AppPositionType =
  // Chat ids are opaque; agent and project ids are rows.
  | { location: "chat"; id: string }
  | { location: "agent" | "project"; id: number }
  | {
      location: "more-agents" | "new-session" | "user-settings" | "shared-chat";
    };

interface NavigationOptions {
  /** Leaves no history entry, so going back skips this address. */
  replace?: boolean;
}

type Router = ReturnType<typeof useRouter>;

/** A row id, or null for a parameter that is absent or is not one. */
function rowId(raw: string | null): number | null {
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : null;
}

/**
 * Which pathname and which parameter name each location lives at.
 *
 * The mirror of the derivation at the bottom of this file, so reading a
 * position and going to one cannot drift apart: they are the same knowledge,
 * stated once in each direction.
 */
function hrefFor(value: AppPositionType): Route {
  switch (value.location) {
    case "chat":
      return routeWithQuery("/app", {
        [SEARCH_PARAM_NAMES.CHAT_ID]: value.id,
      });
    case "agent":
      return routeWithQuery("/app", {
        [SEARCH_PARAM_NAMES.AGENT_ID]: value.id,
      });
    case "project":
      return routeWithQuery("/app", {
        [SEARCH_PARAM_NAMES.PROJECT_ID]: value.id,
      });
    case "more-agents":
      return "/app/agents" as Route;
    case "user-settings":
      return "/app/settings" as Route;
    case "shared-chat":
    case "new-session":
      return "/app" as Route;
  }
}

class AppPosition {
  constructor(
    private value: AppPositionType,
    private router: Router
  ) {}

  /**
   * Where this position lives, for a link rather than a click. An anchor keeps
   * middle-click and open-in-new-tab, which a navigation method cannot.
   */
  href(): Route {
    return hrefFor(this.value);
  }

  // # NOTE (@raunakab):
  // ## Going somewhere
  //
  // Reading is what this position is; the methods below are where the user
  // could go next, which is why they are verbs. Naming them after the location
  // alone would make `chat()` mean the current chat with no argument and a
  // different chat with one — the same word for a question and a command.

  openChat(chatSessionId: string, options?: NavigationOptions) {
    this.go({ location: "chat", id: chatSessionId }, options);
  }

  openAgent(agentId: number, options?: NavigationOptions) {
    this.go({ location: "agent", id: agentId }, options);
  }

  openProject(projectId: number, options?: NavigationOptions) {
    this.go({ location: "project", id: projectId }, options);
  }

  openNewSession(options?: NavigationOptions) {
    this.go({ location: "new-session" }, options);
  }

  private go(
    value: AppPositionType,
    { replace = false }: NavigationOptions = {}
  ) {
    const href = hrefFor(value);
    if (replace) this.router.replace(href);
    else this.router.push(href);
  }

  /**
   * The id of whatever this position names, or null.
   *
   * One accessor per location rather than a predicate plus an untyped `getId`.
   * The pair made every caller ask two questions to get one answer, and nothing
   * stopped it asking the second without the first — reading a chat id while
   * standing in a project type-checked fine.
   */
  agent(): number | null {
    return this.value.location === "agent" ? this.value.id : null;
  }

  project(): number | null {
    return this.value.location === "project" ? this.value.id : null;
  }

  chat(): string | null {
    return this.value.location === "chat" ? this.value.id : null;
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
  const router = useRouter();

  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  // Parsed here so every reader gets the id as what it is. Text that is not a
  // row id names nothing, and reads the same as the parameter being absent.
  const agentId = rowId(searchParams.get(SEARCH_PARAM_NAMES.AGENT_ID));
  const projectId = rowId(searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID));

  // Memoize on the values that determine which AppPosition is constructed.
  // AppPosition is immutable, so same inputs → same instance.
  return useMemo(() => {
    if (pathname.startsWith("/app/shared/")) {
      return new AppPosition({ location: "shared-chat" }, router);
    }
    if (pathname.startsWith("/app/settings")) {
      return new AppPosition({ location: "user-settings" }, router);
    }
    if (pathname.startsWith("/app/agents")) {
      return new AppPosition({ location: "more-agents" }, router);
    }
    if (chatId)
      return new AppPosition({ location: "chat", id: chatId }, router);
    if (agentId)
      return new AppPosition({ location: "agent", id: agentId }, router);
    if (projectId) {
      return new AppPosition({ location: "project", id: projectId }, router);
    }
    return new AppPosition({ location: "new-session" }, router);
  }, [pathname, chatId, agentId, projectId, router]);
}
