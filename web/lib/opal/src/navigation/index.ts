/**
 * All of the app's navigation: eager `go` / `linkTo` / `clampedBack`, the
 * `PendingRoute` loader, and Next's own URL reads and server helpers, so code
 * outside Opal never imports `next/navigation` or `next/link`. See README.md.
 */
export {
  useNavigation,
  useRouteRendering,
  loadPage,
  Navigation,
  type NavigationOptions,
  type LinkProps,
} from "@opal/navigation/hooks";
export {
  NavLink,
  PendingRoute,
  type NavLinkProps,
  type PendingRouteProps,
} from "@opal/navigation/components";
export {
  usePathname,
  useSearchParams,
  useParams,
  useSelectedLayoutSegment,
  useSelectedLayoutSegments,
  redirect,
  permanentRedirect,
  notFound,
  RedirectType,
  type ReadonlyURLSearchParams,
} from "@opal/navigation/next";
