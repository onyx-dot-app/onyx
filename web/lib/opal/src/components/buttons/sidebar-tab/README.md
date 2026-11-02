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
            └─ content row       (icon + title + truncation spacer; see styles.css)
```

- **`sidebar-heavy`** (default) — muted when unselected (text-03/text-02), bold when selected (text-04/text-03)
- **`sidebar-light`** — uniformly muted across all states (text-02/text-02)
- **Disabled** — both variants use text-02 foreground, transparent background, no hover/active states
- **The click target** is an absolutely positioned overlay: a `<Link>` when `href` is set, a `<button>` when only `onClick` is set. Both are keyboard focusable. The overlay stays a sibling of the content, so `rightChildren` can sit above it with `pointer-events-auto` and remain a valid nested control. A passive `Tag` (no `onClick` or `onRemove`) in `rightChildren` lets clicks pass through to the overlay.
- **The overlay's name** comes from `aria-label` for a string label, and from `aria-labelledby` on the content row otherwise. The tab therefore keeps a name when the label is hidden.

## Folded state

A tab inside a sidebar needs no `folded` prop. `SidebarRoot` publishes its fold state as `data-folded` on `.opal-sidebar-root__inner`, and `styles.css` hides the label and `rightChildren` from there. Folding a sidebar therefore re-renders no tabs, and the label fades with the column width transition. Both take the shared `--duration-sidebar-fold` token.

The label stays in the DOM while folded. It is hidden with `visibility: hidden`, which keeps it out of the accessibility tree and out of the tab order, so a screen reader never announces it.

Pass `folded` only to override the sidebar — outside a sidebar, or in a skeleton. It sets `data-folded` on the tab itself, which wins over the sidebar.

The label tooltip is the one part that stays in JS: CSS cannot arm a tooltip. A string label shows in full in a tooltip while the tab is folded, or while the unfolded tab cuts it off with an ellipsis. The tooltip hangs off the overlay, so the whole tab is its anchor. It lives in a small wrapper that subscribes to the fold state and measures the title's overflow on the tab's behalf, so a fold, or a title that starts or stops overflowing, re-renders the wrapper and nothing below it. The wrapper keeps the tooltip mounted and passes `suppressed` otherwise, so hover stays Radix's to track and the tab holds no hover state of its own.

Both tooltips (the folded name and an explicit `tooltip`) wrap the overlay control, not the tab. The tab's own tree shape therefore never depends on whether there is a tooltip, so `children` can switch from a label to an element — an inline rename input — without remounting the row and dropping focus. A disabled tab has no control, so it renders an inert overlay as the trigger when it has a tooltip.

## Props

| Prop            | Type                                 | Default           | Description                                                              |
| --------------- | ------------------------------------ | ----------------- | ------------------------------------------------------------------------ |
| `variant`       | `"sidebar-heavy" \| "sidebar-light"` | `"sidebar-heavy"` | Sidebar color variant                                                    |
| `selected`      | `boolean`                            | `false`           | Active/selected state                                                    |
| `icon`          | `IconFunctionComponent`              | —                 | Left icon                                                                |
| `children`      | `ReactNode`                          | —                 | Label text or custom content                                             |
| `disabled`      | `boolean`                            | `false`           | Disables the tab                                                         |
| `folded`        | `boolean`                            | sidebar state     | Collapses label, shows tooltip on hover. Overrides the enclosing sidebar |
| `nested`        | `boolean`                            | `false`           | Renders spacer instead of icon for indented items                        |
| `href`          | `string`                             | —                 | Client-side navigation URL                                               |
| `onClick`       | `MouseEventHandler`                  | —                 | Click handler                                                            |
| `type`          | `ButtonType`                         | —                 | HTML button type                                                         |
| `rightChildren` | `ReactNode`                          | —                 | Actions rendered on the right side                                       |

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
