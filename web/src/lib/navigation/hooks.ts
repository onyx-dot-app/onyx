"use client";

import { useEffect, useMemo } from "react";
import type { Route } from "next";
import {
  usePathname,
  useRouter,
  useSearchParams,
  useSelectedLayoutSegments,
} from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { routeWithQuery } from "@/lib/routes";

// Navigation within the app writes the URL first and asks Next for the page
// after (`go`, `linkTo`), so the tabs, which read the URL, highlight on the
// click, and `PendingRoute` shows the URL's loader until Next renders the page.
// oxlint `navigation/no-naked-navigation` flags the navigations that skip it:
// `router.push`/`replace`, `next/link` and static internal `href`s.

type Router = ReturnType<typeof useRouter>;

export interface NavigationOptions {
  /** Leaves no history entry, so going back skips this address. */
  replace?: boolean;
  /**
   * The page renders the query on the client, so a change of the query alone
   * needs no router round trip: writing the URL is the whole switch.
   */
  shallow?: boolean;
  /** `false` keeps the scroll position, as for a tab or a query edit. */
  scroll?: boolean;
}

/** Props for a link: spread them on an anchor, a `Button` or a sidebar tab. */
export interface LinkProps<T extends string = string> {
  href: Route<T>;
  onClick: (event: React.MouseEvent<HTMLElement>) => void;
}

/** A URL as pathname and query, the same however it was read. */
function urlKey(pathname: string, search: URLSearchParams): string {
  const query = search.toString();
  return query ? `${pathname}?${query}` : pathname;
}

// A router navigation writes its URL at once and asks the router for the page
// after, which renders a moment later (more on a slow network). Set from that
// click until the route renders (`useRouteRendering`): a click meanwhile must
// go through the router too, or the earlier page would land after it.
let routeNavigationInFlight = false;

/** Calls the router, with options only when set, as callers always did. */
function callRouter<T extends string>(
  router: Router,
  method: "push" | "replace",
  href: Route<T>,
  scroll: boolean | undefined
) {
  if (scroll === undefined) router[method](href);
  else router[method](href, { scroll });
}

function navigate<T extends string>(
  router: Router,
  href: Route<T>,
  { replace = false, shallow = false, scroll }: NavigationOptions = {}
) {
  if (typeof window === "undefined") {
    callRouter(router, replace ? "replace" : "push", href, scroll);
    return;
  }
  // Against the current URL, so a query-only href (`?a=1`) keeps the path.
  const target = new URL(href, window.location.href);
  // A `javascript:` or `data:` URL would run, not navigate.
  if (target.protocol !== "http:" && target.protocol !== "https:") {
    throw new Error(`Refusing to navigate to a ${target.protocol} URL`);
  }
  // Another origin is not a page of this app, and history cannot hold it.
  if (target.origin !== window.location.origin) {
    if (replace) window.location.replace(target.href);
    else window.location.assign(target.href);
    return;
  }
  const herePathname = window.location.pathname;
  const here = urlKey(
    herePathname,
    new URLSearchParams(window.location.search)
  );
  // Already there: a second entry for the same URL would make Back look like
  // it does nothing. A new `#fragment` still counts as a move.
  if (
    urlKey(target.pathname, target.searchParams) === here &&
    target.hash === window.location.hash
  ) {
    return;
  }

  // The URL changes now, so everything that reads it follows the click at
  // once: Next keeps usePathname and useSearchParams in sync with the history
  // API.
  if (replace) window.history.replaceState(null, "", href);
  else window.history.pushState(null, "", href);
  const queryOnly = target.pathname === herePathname;
  if (shallow && queryOnly && !routeNavigationInFlight) return;
  // Only a new route renders later and clears the flag; a move within the
  // route (query or hash) would leave it set.
  if (!queryOnly) routeNavigationInFlight = true;
  callRouter(router, "replace", href, scroll);
}

function isOtherOrigin(href: string): boolean {
  return new URL(href, window.location.href).origin !== window.location.origin;
}

/**
 * Whether a click is a plain left click on a link that opens in this tab and
 * does not download, which a link may take over.
 */
function isPlainClick(event: React.MouseEvent<HTMLElement>): boolean {
  const link = event.currentTarget;
  const target = link.getAttribute("target");
  return (
    !event.defaultPrevented &&
    (target === null || target === "_self") &&
    !link.hasAttribute("download") &&
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

export class Navigation {
  constructor(private router: Router) {}

  // Generic like Next's `router.push`, so a dynamic path such as
  // `/craft/v1/tasks/${id}` type-checks against its route.

  /** Goes to a page of the app. */
  go<T extends string>(href: Route<T>, options?: NavigationOptions) {
    navigate(this.router, href, options);
  }

  /**
   * A link to a page of the app: its `href` (so a new tab or a copied link
   * still works) and a click handler that sends a plain click through `go`.
   * A caller with its own click handling calls `onClick` first.
   */
  linkTo<T extends string>(
    href: Route<T>,
    options?: NavigationOptions
  ): LinkProps<T> {
    return {
      href,
      onClick: (event) => {
        // A modified or middle click keeps the link's own behavior, e.g.
        // opening a new tab, and so does a link to another origin.
        if (!isPlainClick(event) || isOtherOrigin(href)) return;
        event.preventDefault();
        navigate(this.router, href, options);
      },
    };
  }
}

export function useNavigation(): Navigation {
  const router = useRouter();
  return useMemo(() => new Navigation(router), [router]);
}

/**
 * Whether the URL is ahead of the route Next renders: `go()` wrote the URL of
 * a page that has not rendered yet. Call it in a component that the layout at
 * `base` renders (e.g. the chrome), so the rendered segments are read below it.
 */
export function useRouteRendering(base: string): boolean {
  const pathname = usePathname();
  // The rendered tree's segments, which follow the router, not the URL.
  // Route groups name no URL segment.
  const segments = useSelectedLayoutSegments().filter(
    (segment) => !segment.startsWith("(")
  );
  const renderedPathname =
    segments.length > 0 ? `${base}/${segments.join("/")}` : base;
  const rendering = renderedPathname !== pathname;
  useEffect(() => {
    if (!rendering) routeNavigationInFlight = false;
  }, [rendering]);
  return rendering;
}

// "AppPosition" is where in the main application the user currently is. It is
// derived from the URL and nothing else, so any flow that needs to put the user
// somewhere — or to know where they are — states it as a URL and reads it back
// here, rather than keeping a second copy of the answer in component state.

type AppPositionType =
  // Chat ids are opaque; agent and project ids are rows.
  | { location: "chat"; id: string }
  | { location: "agent" | "project"; id: number }
  | {
      location:
        | "more-agents"
        | "new-session"
        | "user-settings"
        | "shared-chat"
        | "plugins";
    };

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
      return "/app/agents";
    case "plugins":
      return "/app/plugins";
    case "user-settings":
      return "/app/settings";
    case "shared-chat":
    case "new-session":
      return "/app";
  }
}

/** Every /app position renders its query on the client, so `go` is shallow. */
type AppNavigationOptions = Omit<NavigationOptions, "shallow">;

class AppPosition {
  constructor(
    private value: AppPositionType,
    private navigation: Navigation
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

  openChat(chatSessionId: string, options?: AppNavigationOptions) {
    this.go({ location: "chat", id: chatSessionId }, options);
  }

  openAgent(agentId: number, options?: AppNavigationOptions) {
    this.go({ location: "agent", id: agentId }, options);
  }

  openProject(projectId: number, options?: AppNavigationOptions) {
    this.go({ location: "project", id: projectId }, options);
  }

  openNewSession(options?: AppNavigationOptions) {
    this.go({ location: "new-session" }, options);
  }

  // ## Linking somewhere
  //
  // A link to a position: its `href` (so a new tab or a copied link still
  // works) and a click handler that sends a plain click through `go`, so it
  // switches at once instead of waiting on a server render. Spread both onto
  // the link; a caller with its own click handling calls `onClick` first.

  linkToChat(chatSessionId: string): AppLinkProps {
    return this.linkTo({ location: "chat", id: chatSessionId });
  }

  linkToAgent(agentId: number): AppLinkProps {
    return this.linkTo({ location: "agent", id: agentId });
  }

  linkToProject(projectId: number): AppLinkProps {
    return this.linkTo({ location: "project", id: projectId });
  }

  linkToNewSession(): AppLinkProps {
    return this.linkTo({ location: "new-session" });
  }

  private linkTo(value: AppPositionType): AppLinkProps {
    return this.navigation.linkTo(hrefFor(value), { shallow: true });
  }

  private go(value: AppPositionType, options?: AppNavigationOptions) {
    // Within /app only the query changes, and the page renders it on the
    // client, so writing the URL is the whole switch.
    this.navigation.go(hrefFor(value), { ...options, shallow: true });
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

  isPlugins(): boolean {
    return this.value.location === "plugins";
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
   * - "Always Start with an Agent" is on (Admin -> Chat Preferences -> Advanced
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

/** Props for a link to an app position; see `AppPosition.linkToChat`. */
export type AppLinkProps = LinkProps;

export function useAppPosition(): AppPosition {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const navigation = useNavigation();

  const chatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  // Parsed here so every reader gets the id as what it is. Text that is not a
  // row id names nothing, and reads the same as the parameter being absent.
  const agentId = rowId(searchParams.get(SEARCH_PARAM_NAMES.AGENT_ID));
  const projectId = rowId(searchParams.get(SEARCH_PARAM_NAMES.PROJECT_ID));

  // Memoize on the values that determine which AppPosition is constructed.
  // AppPosition is immutable, so same inputs → same instance.
  return useMemo(() => {
    if (pathname.startsWith("/app/shared/")) {
      return new AppPosition({ location: "shared-chat" }, navigation);
    }
    if (pathname.startsWith("/app/settings")) {
      return new AppPosition({ location: "user-settings" }, navigation);
    }
    if (pathname === "/app/plugins" || pathname.startsWith("/app/plugins/")) {
      return new AppPosition({ location: "plugins" }, navigation);
    }
    if (pathname.startsWith("/app/agents")) {
      return new AppPosition({ location: "more-agents" }, navigation);
    }
    if (chatId)
      return new AppPosition({ location: "chat", id: chatId }, navigation);
    if (agentId)
      return new AppPosition({ location: "agent", id: agentId }, navigation);
    if (projectId) {
      return new AppPosition(
        { location: "project", id: projectId },
        navigation
      );
    }
    return new AppPosition({ location: "new-session" }, navigation);
  }, [pathname, chatId, agentId, projectId, navigation]);
}
