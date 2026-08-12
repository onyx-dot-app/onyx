# SidebarTab

**Import:** `import { SidebarTab, type SidebarTabProps } from "@opal/components";`

A sidebar navigation tab built on `Interactive.Stateful` > `Interactive.Container`. Designed for admin and app sidebars.

## Architecture

```
div.opal-sidebar-tab      <- folded styling hook (see styles.css)
  └─ Interactive.Stateful        <- variant (sidebar-heavy | sidebar-light), state, disabled
       └─ Interactive.Container  <- rounding, height, width
            ├─ Link?             (absolute overlay for client-side navigation)
            ├─ rightChildren?    (absolute, above Link for inline actions)
            └─ ContentAction     (icon + title + truncation spacer)
```

- **`sidebar-heavy`** (default) — muted when unselected (text-03/text-02), bold when selected (text-04/text-03)
- **`sidebar-light`** — uniformly muted across all states (text-02/text-02)
- **Disabled** — both variants use text-02 foreground, transparent background, no hover/active states
- **Navigation** uses an absolutely positioned `<Link>` overlay rather than `href` on the Interactive element, so `rightChildren` can sit above it with `pointer-events-auto`. A string label is also set as the link's `aria-label`, so the tab keeps a name when the label is hidden.

## Folded state

A tab inside a sidebar needs no `folded` prop. `SidebarRoot` publishes its fold state as `data-folded` on `.opal-sidebar-root__inner`, and `styles.css` hides the label and `rightChildren` from there. Folding a sidebar therefore re-renders no tabs, and the label fades with the 200ms column width transition.

The label stays in the DOM while folded. It is hidden with `visibility: hidden`, which keeps it out of the accessibility tree and out of the tab order, so a screen reader never announces it.

Pass `folded` only to override the sidebar — outside a sidebar, in Storybook, or in a skeleton. It sets `data-folded` on the tab itself, which wins over the sidebar.

The folded-name tooltip is the one part that stays in JS: CSS cannot arm a tooltip. It lives in a small wrapper that subscribes to the fold state on the tab's behalf, so a fold re-renders the wrapper and nothing below it.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"sidebar-heavy" \| "sidebar-light"` | `"sidebar-heavy"` | Sidebar color variant |
| `selected` | `boolean` | `false` | Active/selected state |
| `icon` | `IconFunctionComponent` | — | Left icon |
| `children` | `ReactNode` | — | Label text or custom content |
| `disabled` | `boolean` | `false` | Disables the tab |
| `folded` | `boolean` | sidebar state | Collapses label, shows tooltip on hover. Overrides the enclosing sidebar |
| `nested` | `boolean` | `false` | Renders spacer instead of icon for indented items |
| `href` | `string` | — | Client-side navigation URL |
| `onClick` | `MouseEventHandler` | — | Click handler |
| `type` | `ButtonType` | — | HTML button type |
| `rightChildren` | `ReactNode` | — | Actions rendered on the right side |

## Usage

```tsx
import { SidebarTab } from "@opal/components";
import { SvgSettings, SvgLock } from "@opal/icons";

// Active tab
<SidebarTab icon={SvgSettings} href="/admin/settings" selected>
  Settings
</SidebarTab>

// Muted variant
<SidebarTab icon={SvgSettings} variant="sidebar-light">
  Exit Admin Panel
</SidebarTab>

// Disabled enterprise-only tab
<SidebarTab icon={SvgLock} disabled>
  Groups
</SidebarTab>

// Folded sidebar (icon only, tooltip on hover)
<SidebarTab icon={SvgSettings} href="/admin/settings" folded>
  Settings
</SidebarTab>
```
