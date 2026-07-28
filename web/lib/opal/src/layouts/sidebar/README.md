# SidebarLayouts

**Import:** `import { SidebarLayouts, useSidebarState } from "@opal/layouts";`

Namespaced layout primitives for app sidebars. Provides responsive
positioning (mobile overlay / medium overlay / desktop column), a
scrollable body with scroll-position persistence, and a topbar that
renders a logo + fold toggle.

Fold state is managed by `SidebarStateProvider` (see `@opal/layouts/root`).
All `SidebarLayouts` primitives and any component that calls
`useSidebarState()` must be rendered inside a `SidebarStateProvider`.

## CSS custom properties

The following must be defined by the consuming app:

| Variable | Example | Description |
|---|---|---|
| `--sidebar-width-folded` | `4rem` | Width when the sidebar is collapsed |
| `--sidebar-width-expanded` | `15rem` | Width when the sidebar is open |

## Components

### `SidebarLayouts.Root`

Sidebar entry point. Handles three viewport sizes:

- **Desktop** — normal flex-row participant; width animates between
  `--sidebar-width-folded` and `--sidebar-width-expanded`.
- **Medium** (`≤ 1232 px`) — fixed overlay; a spacer div preserves the
  folded width in the layout flow. Backdrop closes on click.
- **Mobile** (`≤ 724 px`) — full-height fixed overlay with a tinted and
  blurred backdrop that closes on click.

| Prop | Type | Default | Description |
|---|---|---|---|
| `foldable` | `boolean` | `false` | Enable fold/unfold on desktop |
| `children` | `ReactNode` | — | `Header`, `Body`, `Footer`, `Section` |

### `SidebarLayouts.Header`

Topbar (logo + fold button) with optional pinned content below it
(e.g. a search input or new-session button).

| Prop | Type | Default | Description |
|---|---|---|---|
| `renderAppLogo` | `(folded: boolean \| undefined) => IconFunctionComponent` | — | Logo factory; receives the effective fold state (`undefined` when non-foldable) and returns a component rendered at `size={28}` |
| `showLogoWhenFolded` | `boolean` | `true` | When `false`, hides the logo and shows only the fold button when collapsed |
| `children` | `ReactNode` | — | Pinned content below the topbar |

### `SidebarLayouts.Body`

Scrollable content area. Persists scroll position to `sessionStorage`
keyed by `scrollKey` and restores it on pathname changes.

| Prop | Type | Default | Description |
|---|---|---|---|
| `scrollKey` | `string` | — | Unique key for scroll persistence (e.g. `"admin-sidebar"`) |
| `children` | `ReactNode` | — | |

### `SidebarLayouts.Footer`

Pinned content below the scroll area (e.g. user avatar, account popover).

### `SidebarLayouts.Section`

Titled group within the scrollable body. Renders a section header with an
optional hover-revealed action.

| Prop | Type | Default | Description |
|---|---|---|---|
| `title` | `string \| RichStr` | — | Section heading; omit for an untitled spacer |
| `action` | `ReactNode` | — | Optional element shown on hover (e.g. a `+` button) |
| `disabled` | `boolean` | — | Dims the section header to indicate it is unavailable |
| `children` | `ReactNode` | — | |

## Hooks

### `useSidebarState()`

Returns `{ folded, setFolded }`. Must be used within `SidebarStateProvider`.

```ts
import { useSidebarState } from "@opal/layouts";

const { folded, setFolded } = useSidebarState();
```

## Usage

```tsx
import { SidebarLayouts } from "@opal/layouts";
import { renderAppLogo } from "@/lib/app/utils";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

function MySidebar() {
  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root foldable>
      <SidebarLayouts.Header
        renderAppLogo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        <SearchInput />
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey="my-sidebar">
        <SidebarLayouts.Section title="Recent">
          <NavItems />
        </SidebarLayouts.Section>
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        <UserAvatar />
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}
```
