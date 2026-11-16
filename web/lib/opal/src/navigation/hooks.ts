"use client";

import { useEffect, useMemo, useRef, useTransition } from "react";
import type { Route } from "next";
import {
  usePathname,
  useRouter,
  useSelectedLayoutSegments,
} from "next/navigation";

// All of the app's navigation. `go` and `linkTo` write the URL first and ask
// Next for the page after, so everything that reads the URL (the tabs) follows
// the click at once, and `PendingRoute` shows the URL's loader until Next
// renders the page. `clampedBack` goes back without leaving the app. The rest
// are Next's own, here so navigation has one import.

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

// The same for a router request that changes only the query, which renders
// no new route: it runs in a transition (`useNavigation`), and counts here
// until that transition ends.
let queryRequestsInFlight = 0;

/** Runs a router request in the calling `useNavigation`'s transition. */
type QueryRequestRunner = (request: () => void) => void;

// Each history entry `go` creates records its depth into the app in
// `history.state`: 1 for the first page reached from a load, 2 for the next.
// An entry `go` did not create (a page load, a typed URL, a link from another
// site) has none and counts as 0, so `clampedBack` never leaves the app.
const DEPTH_KEY = "opalNavigationDepth";

function currentDepth(): number {
  const state: unknown = window.history.state;
  if (typeof state !== "object" || state === null || !(DEPTH_KEY in state)) {
    return 0;
  }
  const depth = state[DEPTH_KEY];
  return typeof depth === "number" ? depth : 0;
}

// Next writes its own history state when it commits a navigation, which drops
// the depth. The last `go` keeps it here, and `useRouteRendering` writes it
// back after the commit. Back or Forward clears it, so it never lands on
// another entry with the same URL.
let depthStamp: { href: string; depth: number } | null = null;

function restoreDepth() {
  if (
    depthStamp === null ||
    window.location.href !== depthStamp.href ||
    currentDepth() === depthStamp.depth
  ) {
    return;
  }
  // Next's own fields stay as they are.
  const state: unknown = window.history.state;
  const current = typeof state === "object" ? state : null;
  window.history.replaceState(
    Object.assign({}, current, { [DEPTH_KEY]: depthStamp.depth }),
    ""
  );
}

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
  runQueryRequest: QueryRequestRunner,
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
  const hereSearch = window.location.search;
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
  // API. The entry records how deep into the app it is, for `clampedBack`.
  const depth = replace ? currentDepth() : currentDepth() + 1;
  const state = { [DEPTH_KEY]: depth };
  if (replace) window.history.replaceState(state, "", href);
  else window.history.pushState(state, "", href);
  depthStamp = { href: window.location.href, depth };
  const queryOnly = target.pathname === herePathname;
  // Any router request can land after a later shallow switch, so a shallow
  // switch goes through the router too while one is in flight.
  const requestInFlight = routeNavigationInFlight || queryRequestsInFlight > 0;
  if (shallow && queryOnly && !requestInFlight) return;
  if (!queryOnly) {
    routeNavigationInFlight = true;
    callRouter(router, "replace", href, scroll);
    return;
  }
  // A move of the hash alone requests nothing that could land late.
  if (target.search === hereSearch) {
    callRouter(router, "replace", href, scroll);
    return;
  }
  runQueryRequest(() => callRouter(router, "replace", href, scroll));
}

function isOtherOrigin(href: string): boolean {
  return new URL(href, window.location.href).origin !== window.location.origin;
}

/** A `#fragment` on this page, which the browser scrolls to itself. */
function isSamePageHash(href: string): boolean {
  const target = new URL(href, window.location.href);
  return (
    target.hash !== "" &&
    target.pathname === window.location.pathname &&
    target.search === window.location.search
  );
}

/**
 * A full page load: another origin, a backend route (`/api/…`), or a page
 * whose client state must start over (e.g. after sign-out). No loader shows,
 * because the document itself is replaced. For code outside a component;
 * a component calls `useNavigation().load()`.
 */
export function loadPage(
  url: string,
  { replace = false }: Pick<NavigationOptions, "replace"> = {}
) {
  if (replace) window.location.replace(url);
  else window.location.assign(url);
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
  constructor(
    private router: Router,
    private runQueryRequest: QueryRequestRunner
  ) {}

  // Generic like Next's `router.push`, so a dynamic path such as
  // `/craft/v1/tasks/${id}` type-checks against its route.

  /** Goes to a page of the app. */
  go<T extends string>(href: Route<T>, options?: NavigationOptions) {
    navigate(this.router, this.runQueryRequest, href, options);
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
        // opening a new tab, and so does a link to another origin or to a
        // fragment of this page (the browser scrolls to it).
        if (
          !isPlainClick(event) ||
          isOtherOrigin(href) ||
          isSamePageHash(href)
        ) {
          return;
        }
        event.preventDefault();
        navigate(this.router, this.runQueryRequest, href, options);
      },
    };
  }

  /** Renders the current page's server components again, with fresh data. */
  refresh() {
    this.router.refresh();
  }

  /** Fetches a page's shell (down to its `loading.tsx`) ahead of a click. */
  prefetch<T extends string>(href: Route<T>) {
    this.router.prefetch(href);
  }

  /** A full page load; see `loadPage`. */
  load(url: string, options?: Pick<NavigationOptions, "replace">) {
    loadPage(url, options);
  }

  /** Loads the current document again, which resets all client state. */
  reload() {
    window.location.reload();
  }

  /**
   * Goes back when the previous history entry is a page of the app, and
   * otherwise to `fallback` in place of this entry, so it never leaves the
   * app (to another site, or to an empty tab).
   */
  clampedBack<T extends string>(fallback: Route<T>) {
    if (typeof window !== "undefined" && currentDepth() > 0) {
      window.history.back();
      return;
    }
    navigate(this.router, this.runQueryRequest, fallback, {
      replace: true,
    });
  }
}

export function useNavigation(): Navigation {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  // This hook's query requests still counted in `queryRequestsInFlight`.
  const pendingQueryRequests = useRef(0);
  const navigation = useMemo(
    () =>
      new Navigation(router, (request) => {
        pendingQueryRequests.current += 1;
        queryRequestsInFlight += 1;
        startTransition(request);
      }),
    [router]
  );
  useEffect(() => {
    if (isPending) return;
    queryRequestsInFlight -= pendingQueryRequests.current;
    pendingQueryRequests.current = 0;
  }, [isPending]);
  // Unmounting mid-request stops counting it.
  useEffect(
    () => () => {
      queryRequestsInFlight -= pendingQueryRequests.current;
      pendingQueryRequests.current = 0;
    },
    []
  );
  return navigation;
}

/**
 * A pathname in one canonical encoding: each segment decoded (a malformed one
 * stays as it is), then encoded again. `%31` and `1` match, and an encoded
 * `/` stays inside its segment, so `a%2Fb` is not `a/b`.
 */
function pathSegments(pathname: string): string {
  return pathname
    .split("/")
    .map((segment) => {
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    })
    .map(encodeURIComponent)
    .join("/");
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
  // Segments may come decoded while the URL keeps `%31`, so compare both
  // decoded, segment by segment.
  const rendering = pathSegments(renderedPathname) !== pathSegments(pathname);
  useEffect(() => {
    if (!rendering) routeNavigationInFlight = false;
  }, [rendering]);
  // After each commit, since Next's own history write drops the depth.
  useEffect(() => {
    if (!rendering) restoreDepth();
  });
  useEffect(() => {
    const forget = () => {
      depthStamp = null;
    };
    window.addEventListener("popstate", forget);
    return () => window.removeEventListener("popstate", forget);
  }, []);
  return rendering;
}
