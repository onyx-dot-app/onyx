# Navigation

**Import:** `import { useNavigation, NavLink, PendingRoute, usePathname } from "@opal/navigation";`

All of the app's navigation lives here. Outside this module, nothing imports
`next/navigation` or `next/link`, writes `window.location`, links to a page with
a static `href`, or calls the router's `push` / `replace` / `back` or `history`'s
`pushState` / `replaceState` / `back` (oxlint
`navigation/no-naked-navigation`).

Next's `router.push` changes the URL only when the next page can render, so the
tabs (which read the URL) and the page's loader wait on the network. This module
makes navigation eager:

1. `go` writes the URL at once (`history.pushState`), so everything that reads
   it follows the click.
2. It then calls `router.replace`, so Next fetches and renders the page.
3. While the URL is ahead of the rendered route, `PendingRoute` shows the URL's
   loader.

## useNavigation

```tsx
const navigation = useNavigation();

navigation.go("/admin/users");
navigation.go(`/admin/groups/${id}`, { replace: true, scroll: false });

<Button {...navigation.linkTo("/admin/billing")}>Billing</Button>

<Button onClick={() => navigation.clampedBack("/app/agents")}>Back</Button>
```

| Member | What it does |
| --- | --- |
| `go(href, options?)` | Goes to a page of the app: the URL first, then the page. |
| `linkTo(href, options?)` | `{ href, onClick }` for a link, a `Button` or a sidebar tab. A plain click goes through `go`; a modified click, `target="_blank"`, `download` and another origin keep the browser's behavior. |
| `clampedBack(fallback)` | Goes back when this history entry was made by `go` (see "clampedBack and history"), and otherwise to `fallback` (replacing this entry), so it never leaves the app. |
| `refresh()` | Renders the current page's server components again, with fresh data. |
| `prefetch(href)` | Fetches a page's shell (down to its `loading.tsx`) ahead of a click. |
| `load(url, { replace? })` | A full page load: another origin, a backend route (`/api/…`), or a reset of the app's state. `loadPage` does the same outside a component. |
| `reload()` | Loads the current document again. |

Options for `go` and `linkTo`:

| Option | Default | What it does |
| --- | --- | --- |
| `replace` | `false` | Replaces this history entry instead of adding one. |
| `scroll` | Next's | `false` keeps the scroll position (tabs, query edits). |
| `shallow` | `false` | For a change of the query alone on a page that renders the query itself: writing the URL is the whole switch, with no router round trip. |

A link to another origin and a URL that is not http(s) are not navigations of
the app: `go` loads another origin in full and refuses the rest.

## Next's helpers

`usePathname`, `useSearchParams`, `useParams`, `useSelectedLayoutSegment(s)`,
`redirect`, `permanentRedirect`, `notFound`, `RedirectType` and
`ReadonlyURLSearchParams` are Next's own, re-exported unchanged. `go` writes the
URL first, so `usePathname` and `useSearchParams` follow a click at once.

## NavLink

`next/link` whose plain click goes through `go`. It takes `href`, `replace`,
`shallow`, `scroll` and Link's other props, except its own navigation props
(`as`, `legacyBehavior`, `onNavigate`).

```tsx
<NavLink href="/app/agents">Agents</NavLink>
```

## PendingRoute

For a layout (a chrome), not a page. It wraps the layout's pages and shows
`loader` while the URL names a route Next has not rendered yet. The page being
left stays mounted, hidden, so going back finds it as it was. Its effects keep
running meanwhile: an effect that acts on the URL must check that the URL still
names its page.

```tsx
<PendingRoute base="/admin" loader={<PageLoader />}>
  {children}
</PendingRoute>
```

`base` is the path of the layout that renders it. `useRouteRendering(base)` is
the check it uses, for a layout that needs it too.

## clampedBack and history

Each entry `go` creates records its depth into the app in `history.state`. An
entry `go` did not create (a page load, a typed URL, a link from another site)
counts as 0, so `clampedBack` from it goes to `fallback`. Next rewrites
`history.state` when it commits a navigation; `useRouteRendering` writes the
depth back after the commit, so it holds on pages under a `PendingRoute`. On
other pages `clampedBack` goes to `fallback`.
