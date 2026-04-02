# SidebarTab

**Import:** `import { SidebarTab, type SidebarTabProps } from "@opal/components";`

A sidebar navigation tab built on `Interactive.Stateful` > `Interactive.Container`. Designed for admin and app sidebars.

## Architecture

```
div.relative
  └─ Interactive.Stateful        <- variant (sidebar-heavy | sidebar-light), state, disabled
       └─ Interactive.Container  <- rounding, height, width
            ├─ Link?             (absolute overlay for client-side navigation)
            ├─ rightChildren?    (absolute, above Link for inline actions)
            └─ ContentAction     (icon + title + truncation spacer)
```

- **`sidebar-heavy`** (default) — muted when unselected (text-03/text-02), bold when selected (text-04/text-03)
- **`sidebar-light`** (via `lowlight`) — uniformly muted across all states (text-02/text-02)
- **Disabled** — both variants use text-02 foreground, transparent background, no hover/active states
- **Navigation** uses an absolutely positioned `<Link>` overlay rather than `href` on the Interactive element, so `rightChildren` can sit above it with `pointer-events-auto`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `icon` | `IconFunctionComponent` | — | Left icon |
| `children` | `ReactNode` | — | Label text or custom content |
| `selected` | `boolean` | `false` | Active/selected state |
| `lowlight` | `boolean` | `false` | Uses muted `sidebar-light` variant |
| `disabled` | `boolean` | `false` | Disables the tab |
| `folded` | `boolean` | `false` | Collapses label, shows tooltip on hover |
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

// Disabled enterprise-only tab
<SidebarTab icon={SvgLock} disabled>
  Groups
</SidebarTab>

// Folded sidebar (icon only, tooltip on hover)
<SidebarTab icon={SvgSettings} href="/admin/settings" folded>
  Settings
</SidebarTab>
```
