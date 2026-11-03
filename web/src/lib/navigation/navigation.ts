"use client";

import { useEffect, useMemo } from "react";
import type { Route } from "next";
import {
  usePathname,
  useRouter,
  useSearchParams,
  useSelectedLayoutSegments,
} from "next/navigation";

// Every navigation in the web app goes through this module. A navigation
// writes the URL first and asks Next for the page after, so the URL, the
// sidebar and the page's loader follow a click at once; `PendingRoute` shows
// that loader until Next renders the page. Code outside `lib/navigation` reads
// and writes the URL only through here (oxlint `navigation/no-naked-navigation`).

type Router = ReturnType<typeof useRouter>;

export interface NavigationOptions {
  /** Leaves no history entry, so going back skips this address. */
  replace?: boolean;
  /**
   * The page renders the query on the client, so a change of the query alone
   * needs no router round trip: writing the URL is the whole switch.
   */
  shallow?: boolean;
}

/** Props for a link: spread them on an anchor, a `Button` or a sidebar tab. */
export interface LinkProps {
  href: Route;
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

function navigate(
  router: Router,
  href: Route,
  { replace = false, shallow = false }: NavigationOptions = {}
) {
  if (typeof window === "undefined") {
    if (replace) router.replace(href);
    else router.push(href);
    return;
  }
  const target = new URL(href, window.location.origin);
  const here = urlKey(
    window.location.pathname,
    new URLSearchParams(window.location.search)
  );
  // Already there: a second entry for the same URL would make Back look like
  // it does nothing.
  if (urlKey(target.pathname, target.searchParams) === here) return;

  // The URL changes now, so everything that reads it follows the click at
  // once: Next keeps usePathname and useSearchParams in sync with the history
  // API.
  if (replace) window.history.replaceState(null, "", href);
  else window.history.pushState(null, "", href);
  const queryOnly = target.pathname === window.location.pathname;
  if (shallow && queryOnly && !routeNavigationInFlight) return;
  routeNavigationInFlight = true;
  router.replace(href);
}

/** Whether a click is a plain left click, which a link may take over. */
function isPlainClick(event: React.MouseEvent<HTMLElement>): boolean {
  return (
    !event.defaultPrevented &&
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

export class Navigation {
  constructor(private router: Router) {}

  /** Goes to a page of the app. */
  go(href: Route, options?: NavigationOptions) {
    navigate(this.router, href, options);
  }

  /**
   * A link to a page of the app: its `href` (so a new tab or a copied link
   * still works) and a click handler that sends a plain click through `go`.
   * A caller with its own click handling calls `onClick` first.
   */
  linkTo(href: Route, options?: NavigationOptions): LinkProps {
    return {
      href,
      onClick: (event) => {
        // A modified or middle click keeps the link's own behavior, e.g.
        // opening a new tab.
        if (!isPlainClick(event)) return;
        event.preventDefault();
        navigate(this.router, href, options);
      },
    };
  }

  back() {
    this.router.back();
  }

  /** Renders the current page's server components again, with fresh data. */
  refresh() {
    this.router.refresh();
  }

  prefetch(href: Route) {
    this.router.prefetch(href);
  }

  /**
   * A full page load: another origin, a backend route (`/api/…`), or a page
   * whose client state must start over (e.g. after sign-out). No loader
   * shows, because the document itself is replaced.
   */
  load(
    url: string,
    { replace = false }: Pick<NavigationOptions, "replace"> = {}
  ) {
    if (replace) window.location.replace(url);
    else window.location.assign(url);
  }

  reload() {
    window.location.reload();
  }
}

export function useNavigation(): Navigation {
  const router = useRouter();
  return useMemo(() => new Navigation(router), [router]);
}

/** The current URL. It follows a click at once, before the page renders. */
export interface CurrentUrl {
  pathname: string;
  searchParams: URLSearchParams;
  /** Pathname and query, e.g. for a sign-in's return address. */
  href: string;
}

export function useCurrentUrl(): CurrentUrl {
  const pathname = usePathname();
  const readonlyParams = useSearchParams();
  return useMemo(() => {
    const searchParams = new URLSearchParams(readonlyParams.toString());
    return { pathname, searchParams, href: urlKey(pathname, searchParams) };
  }, [pathname, readonlyParams]);
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
