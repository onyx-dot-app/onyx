# SidebarLayouts

**Import:** `import { SidebarLayouts, SidebarWrapper, useSidebarState, useSidebarFolded } from "@opal/layouts";`

Namespaced layout primitives for app sidebars. Provides persistent fold state
with a keyboard shortcut, mobile/medium/desktop responsive positioning, a
scrollable body with scroll-position persistence, and a structural chrome
component (`SidebarWrapper`) that can be used standalone.

## CSS custom properties

The following must be defined by the consuming app:

| Variable | Example | Description |
|---|---|---|
| `--sidebar-width-folded` | `4rem` | Width when the sidebar is collapsed |
| `--sidebar-width-expanded` | `15rem` | Width when the sidebar is open |

## Components

### `SidebarLayouts.StateProvider`

Root state provider. Manages the sidebar fold state and registers the
`Cmd/Ctrl+E` keyboard shortcut. Must wrap all other `SidebarLayouts`
primitives and any component that calls `useSidebarState()`.

| Prop | Type | Default | Description |
|---|---|---|---|
| `defaultFolded` | `boolean` | `false` | Initial fold state, typically read from a persisted cookie |
| `onFoldedChange` | `(folded: boolean) => void` | — | Called after every fold state change, e.g. to write back to a cookie |
| `children` | `ReactNode` | — | |

### `SidebarLayouts.Root`

Sidebar entry point. Handles three viewport sizes:

- **Desktop** — normal flex-row participant; width animates between
  `--sidebar-width-folded` and `--sidebar-width-expanded`.
- **Medium** (`≤ 1232 px`) — fixed overlay; a spacer div preserves the
  folded width in the layout flow. Blur-only backdrop closes on click.
- **Mobile** (`≤ 724 px`) — full-height fixed overlay with a tinted and
  blurred backdrop that closes on click.

| Prop | Type | Default | Description |
|---|---|---|---|
| `foldable` | `boolean` | `false` | Enable fold/unfold on desktop |
| `logo` | `(folded: boolean \| undefined) => ReactNode` | — | Logo render function; receives current fold state |
| `showLogoWhenFolded` | `boolean` | `true` | When `false`, hides the logo and shows only the close button when folded |
| `children` | `ReactNode` | — | `Header`, `Body`, `Footer` |

### `SidebarLayouts.Header`

Pinned content above the scroll area (e.g. search input, new-session button).

### `SidebarLayouts.Body`

Scrollable content area. Persists scroll position to `sessionStorage` keyed
by `scrollKey` and restores it on pathname changes.

| Prop | Type | Default | Description |
|---|---|---|---|
| `scrollKey` | `string` | — | Unique key for scroll persistence (e.g. `"admin-sidebar"`) |
| `children` | `ReactNode` | — | |

### `SidebarLayouts.Footer`

Pinned content below the scroll area (e.g. user avatar, account popover).

### `SidebarWrapper`

The structural chrome used internally by `SidebarLayouts.Root`. Export it
directly when you need to drive fold state yourself rather than through the
provider (e.g. `AppSidebar` which reads `useSidebarFolded()` directly).

| Prop | Type | Default | Description |
|---|---|---|---|
| `folded` | `boolean \| undefined` | — | `undefined` = non-foldable (no button shown) |
| `onFoldClick` | `() => void` | — | Toggle callback; omit for non-foldable |
| `logo` | `(folded: boolean \| undefined) => ReactNode` | — | Logo render function |
| `showLogoWhenFolded` | `boolean` | `true` | See `Root` |
| `children` | `ReactNode` | — | `Header`, `Body`, `Footer` content |

## Hooks

### `useSidebarState()`

Returns `{ folded, setFolded }`. Must be used within `StateProvider`.

```ts
import { useSidebarState } from "@opal/layouts";

const { folded, setFolded } = useSidebarState();
```

### `useSidebarFolded()`

Returns the **effective** fold state for content rendering. On mobile this is
always `false` — the overlay transform handles visibility instead. Use this
inside `Body` children to conditionally hide content when collapsed.

```ts
import { useSidebarFolded } from "@opal/layouts";

const folded = useSidebarFolded();
```

## Usage

### With `SidebarLayouts.Root` (admin sidebar pattern)

```tsx
import { SidebarLayouts, useSidebarFolded } from "@opal/layouts";

function MySidebar() {
  const folded = useSidebarFolded();

  return (
    <SidebarLayouts.Root
      logo={(f) => <MyLogo folded={f} />}
    >
      <SidebarLayouts.Header>
        {folded ? <IconButton /> : <SearchInput />}
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey="my-sidebar">
        <NavItems />
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        <UserAvatar />
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}
```

### With `SidebarWrapper` directly (app sidebar pattern)

```tsx
import { SidebarWrapper, useSidebarFolded, useSidebarState } from "@opal/layouts";

function AppSidebarShell() {
  const folded = useSidebarFolded();
  const { setFolded } = useSidebarState();

  return (
    <SidebarWrapper
      folded={folded}
      onFoldClick={() => setFolded((p) => !p)}
      logo={(f) => <MyLogo folded={f} />}
    >
      <SidebarBody />
    </SidebarWrapper>
  );
}
```

### Persisting fold state

```tsx
import { SidebarLayouts } from "@opal/layouts";
import Cookies from "js-cookie";

function AppSidebarStateProvider({ children }: { children: React.ReactNode }) {
  const [defaultFolded] = useState(() =>
    typeof window !== "undefined" &&
    (Cookies.get("sidebarIsToggled") === "true" ||
      localStorage.getItem("sidebarIsToggled") === "true")
  );

  return (
    <SidebarLayouts.StateProvider
      defaultFolded={defaultFolded}
      onFoldedChange={(folded) => {
        const v = String(folded);
        Cookies.set("sidebarIsToggled", v, { expires: 365 });
        localStorage.setItem("sidebarIsToggled", v);
      }}
    >
      {children}
    </SidebarLayouts.StateProvider>
  );
}
```
