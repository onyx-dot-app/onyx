# RootLayout

**Import:** `import { RootLayout } from "@opal/layouts";`

Namespaced layout primitives for the app shell. Provides a full-viewport flex
row with a controlled sidebar, optional permanent panels, and a main content
area with optional pinned header/footer bars.

## Components

### Root

Full-viewport flex row that wraps all other `RootLayout` primitives.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `children` | `ReactNode` | — | `Sidebar`, `LeftPanel`, `MainContent`, `RightPanel` |

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

### MainContent

`flex-1` block that fills the remaining horizontal space.

### LeftPanel / RightPanel

Permanent `shrink-0` columns that push `MainContent` rather than overlaying it.
Width is caller-supplied via `className` (e.g. `className="w-80"`).

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `className` | `string` | — | Width and any other overrides (twMerge applied) |
| `children` | `ReactNode` | — | Panel content |

### Header

Pinned `shrink-0` top bar inside `MainContent`. Use inside a `flex flex-col`
content wrapper so it stays above the scrollable area.

### Footer

Pinned `shrink-0` bottom bar inside `MainContent`.

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
  <RootLayout.MainContent>
    {children}
  </RootLayout.MainContent>
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
  <RootLayout.MainContent>
    {children}
  </RootLayout.MainContent>
  <RootLayout.RightPanel className="w-80">
    <DetailPanel />
  </RootLayout.RightPanel>
</RootLayout.Root>
```

### With header and footer

```tsx
<RootLayout.Root>
  <RootLayout.Sidebar folded={folded} onFoldToggle={toggle}>
    <MySidebarShell />
  </RootLayout.Sidebar>
  <RootLayout.MainContent>
    <RootLayout.Header>
      <AppHeader />
    </RootLayout.Header>
    <div className="flex-1 overflow-auto">
      {children}
    </div>
    <RootLayout.Footer extraPadding={!isActiveChat}>
      <AppFooter />
    </RootLayout.Footer>
  </RootLayout.MainContent>
</RootLayout.Root>
```
