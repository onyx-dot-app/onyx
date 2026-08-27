# SidebarTab

**Import:** `import { SidebarTab, type SidebarTabProps } from "@opal/components";`

A sidebar navigation tab built on `Interactive.Stateful` > `Interactive.Container`. Designed for admin and app sidebars.

## Architecture

```
div.opal-sidebar-tab      <- folded styling hook (see styles.css)
  └─ Interactive.Stateful        <- variant (sidebar-heavy | sidebar-light), state, disabled
       └─ Interactive.Container  <- rounding, height, width
            ├─ Link | button?    (absolute overlay — the click target; also the tooltip trigger)
            ├─ rightChildren?    (absolute, above the overlay for inline actions)
            └─ ContentAction     (icon + title + truncation spacer)
```

- **`sidebar-heavy`** (default) — muted when unselected (text-03/text-02), bold when selected (text-04/text-03)
- **`sidebar-light`** — uniformly muted across all states (text-02/text-02)
- **Disabled** — both variants use text-02 foreground, transparent background, no hover/active states
- **The click target** is an absolutely positioned overlay: a `<Link>` when `href` is set, a `<button>` when only `onClick` is set. Both are keyboard focusable. The overlay stays a sibling of the content, so `rightChildren` can sit above it with `pointer-events-auto` and remain a valid nested control.
- **The overlay's name** comes from `aria-label` for a string label, and from `aria-labelledby` on the content row otherwise. The tab therefore keeps a name when the label is hidden.

## Folded state

A tab inside a sidebar needs no `folded` prop. `SidebarRoot` publishes its fold state as `data-folded` on `.opal-sidebar-root__inner`, and `styles.css` hides the label and `rightChildren` from there. Folding a sidebar therefore re-renders no tabs, and the label fades with the 200ms column width transition.

The label stays in the DOM while folded. It is hidden with `visibility: hidden`, which keeps it out of the accessibility tree and out of the tab order, so a screen reader never announces it.

Pass `folded` only to override the sidebar — outside a sidebar, in Storybook, or in a skeleton. It sets `data-folded` on the tab itself, which wins over the sidebar.

The folded-name tooltip is the one part that stays in JS: CSS cannot arm a tooltip. It lives in a small wrapper that subscribes to the fold state on the tab's behalf, so a fold re-renders the wrapper and nothing below it. The wrapper keeps the tooltip mounted and passes `suppressed` while the tab is unfolded, so hover stays Radix's to track and an unfolded tab holds no hover state of its own.

Both tooltips (the folded name and an explicit `tooltip`) wrap the overlay control, not the tab. The tab's own tree shape therefore never depends on whether there is a tooltip, so `children` can switch from a label to an element — an inline rename input — without remounting the row and dropping focus. A disabled tab has no control, so it renders an inert overlay as the trigger when it has a tooltip.

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
