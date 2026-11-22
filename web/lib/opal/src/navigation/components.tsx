"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import type { Route } from "next";
import {
  type NavigationOptions,
  useNavigation,
  useRouteRendering,
} from "@opal/navigation/hooks";

export interface PendingRouteProps {
  /** The path of the layout that renders this, e.g. `/admin`. */
  base: string;
  /** The loader for the URL's page, shown until that page renders. */
  loader: ReactNode;
  children: ReactNode;
}

/**
 * A layout's pages behind the URL: while the URL's route renders, its loader
 * shows. The page being left stays mounted underneath, so going back to it
 * finds it as it was (an unsaved draft included).
 */
export function PendingRoute({ base, loader, children }: PendingRouteProps) {
  const rendering = useRouteRendering(base);
  return (
    <>
      {rendering && loader}
      <div className={rendering ? "hidden" : "contents"}>{children}</div>
    </>
  );
}

export interface NavLinkProps<T extends string = string>
  // `go` makes the navigation, so Link's own navigation props never apply,
  // and `href` is the only address.
  extends
    Omit<
      React.ComponentProps<typeof Link>,
      "href" | "as" | "legacyBehavior" | "replace" | "scroll" | "onNavigate"
    >,
    NavigationOptions {
  href: Route<T>;
}

/** A Next link whose plain click goes through `Navigation.go`. */
export function NavLink<T extends string>({
  href,
  replace,
  shallow,
  scroll,
  onClick,
  ...props
}: NavLinkProps<T>) {
  const link = useNavigation().linkTo(href, { replace, shallow, scroll });
  return (
    <Link
      {...props}
      href={link.href}
      onClick={(event) => {
        onClick?.(event);
        link.onClick(event);
      }}
    />
  );
}
