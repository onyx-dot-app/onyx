# RootLayout

**Import:** `import { RootLayout } from "@opal/layouts";`

Namespaced layout primitives for the app shell. Provides a full-viewport flex
row with a controlled sidebar, optional permanent panels, and an `App` column
that contains a pinned header, a scrollable main content area, and a pinned
footer.

## Components

### Root

Full-viewport flex row that wraps all other `RootLayout` primitives.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `children` | `ReactNode` | — | `Sidebar`, `LeftPanel`, `App`, `RightPanel` |

### Sidebar

Controlled sidebar that handles three viewport sizes:

- **Desktop** — normal flex-row flow; no backdrop.
- **Medium** (`≤ 1232 px`) — fixed overlay; a spacer div holds the folded
  width in the layout. Blur-only backdrop closes on click.
- **Mobile** (`≤ 724 px`) — full-height fixed overlay with a tinted + blurred
  backdrop that closes on click. `useSidebarFolded()` always returns `false`
  here (content is always expanded; the overlay handles visibility).

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `folded` | `boolean` | — | Current fold state — controlled by the consumer |
| `onFoldToggle` | `() => void` | — | Called when the sidebar should toggle |
| `children` | `ReactNode` | — | Sidebar shell and body content |

### App

`flex-1 flex-col` block that fills the remaining horizontal space between
`Sidebar` and any panels. Use this as the direct child of `Root` to wrap
`Header`, `MainContent`, and `Footer`. Accepts all standard `div` props
(e.g. `className`, `data-*`, `onMouseDown`) for consumer-level overrides.

### MainContent

`flex-1 overflow-auto` scrollable slot inside `App`. Place page content here.
Accepts all standard `div` props.

### LeftPanel / RightPanel

Permanent `shrink-0` columns that push `App` rather than overlaying it.
Width is caller-supplied via `className` (e.g. `className="w-80"`).

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `className` | `string` | — | Width and any other overrides (twMerge applied) |
| `children` | `ReactNode` | — | Panel content |

### Header

Pinned `shrink-0` top bar inside `App`.

### Footer

Pinned `shrink-0` bottom bar inside `App`.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `extraPadding` | `boolean` | `false` | Adds `14 px` top padding for shadow breathing room above the input bar |
| `children` | `ReactNode` | — | Footer content |

## Hooks

### `useSidebarFolded()`

Returns the **effective** fold state for sidebar body content. Use this to
conditionally hide content that shouldn't render when the sidebar is collapsed.
On mobile this always returns `false` (see `Sidebar` above).

```ts
import { useSidebarFolded } from "@opal/layouts";

function SidebarBody() {
  const folded = useSidebarFolded();
  return folded ? null : <SectionContent />;
}
```

## Usage

### Basic

```tsx
import { RootLayout } from "@opal/layouts";

<RootLayout.Root>
  <RootLayout.Sidebar folded={folded} onFoldToggle={toggle}>
    <MySidebarShell />
  </RootLayout.Sidebar>
  <RootLayout.App>
    <RootLayout.Header>
      <AppHeader />
    </RootLayout.Header>
    <RootLayout.MainContent>
      {children}
    </RootLayout.MainContent>
    <RootLayout.Footer>
      <AppFooter />
    </RootLayout.Footer>
  </RootLayout.App>
</RootLayout.Root>
```

### With panels

```tsx
<RootLayout.Root>
  <RootLayout.Sidebar folded={folded} onFoldToggle={toggle}>
    <MySidebarShell />
  </RootLayout.Sidebar>
  <RootLayout.LeftPanel className="w-64">
    <FilterPanel />
  </RootLayout.LeftPanel>
  <RootLayout.App>
    <RootLayout.MainContent>
      {children}
    </RootLayout.MainContent>
  </RootLayout.App>
  <RootLayout.RightPanel className="w-80">
    <DetailPanel />
  </RootLayout.RightPanel>
</RootLayout.Root>
```

### With consumer-level overrides on App

```tsx
<RootLayout.App
  className="@container relative"
  data-main-container
  onMouseDown={handleMouseDown}
  onMouseUp={handleMouseUp}
>
  <RootLayout.Header><AppHeader /></RootLayout.Header>
  <RootLayout.MainContent>{children}</RootLayout.MainContent>
  <RootLayout.Footer><AppFooter /></RootLayout.Footer>
</RootLayout.App>
```
