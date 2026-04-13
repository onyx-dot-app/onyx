# Interactive.Stateful

**Import:** `import { Interactive } from "@opal/core";` — use as `Interactive.Stateful`.

Stateful interactive surface primitive for elements that maintain a value state (empty/filled/selected). Used for toggles, sidebar items, and selectable list rows. Applies variant/state color styling via CSS data-attributes and merges onto a single child element via Radix `Slot`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"select-light" \| "select-heavy" \| "select-card" \| "select-tinted" \| "select-filter" \| "sidebar-heavy" \| "sidebar-light"` | `"select-heavy"` | Color variant |
| `state` | `"empty" \| "filled" \| "selected"` | `"empty"` | Current value state |
| `interaction` | `"rest" \| "hover" \| "active"` | `"rest"` | JS-controlled interaction override |
| `group` | `string` | — | Tailwind group class for `group-hover:*` |
| `disabled` | `boolean` | `false` | Disables the element |
| `href` | `string` | — | URL for link behavior |
| `target` | `string` | — | Link target (e.g. `"_blank"`) |

## Variants

- **`select-light`** — Transparent selected background. For inline toggles.
- **`select-heavy`** — Tinted selected background (`action-link-01`). For list rows, model pickers, buttons.
- **`select-card`** — Like `select-heavy`, but the filled state gets a visible background (`background-tint-00`) with neutral foreground. Designed for larger surfaces (cards) where background carries more of the visual distinction than foreground color alone.
- **`select-tinted`** — Like `select-heavy` but with a tinted rest background (`background-tint-01`).
- **`select-filter`** — Like `select-tinted` for empty/filled; selected state uses inverted backgrounds and inverted text.
- **`sidebar-heavy`** — Sidebar navigation: muted when unselected, bold when selected.
- **`sidebar-light`** — Sidebar navigation: uniformly muted across all states.

## State attribute

Uses `data-interactive-state` (not `data-state`) to avoid conflicts with Radix UI, which injects its own `data-state` on trigger elements.

## CSS custom properties

Sets `--interactive-foreground` and `--interactive-foreground-icon` per variant/state. In the `empty` state, icon color (`--text-03`) is intentionally lighter than text color (`--text-04`).

## Usage

```tsx
<Interactive.Stateful variant="select-heavy" state="selected" onClick={toggle}>
  <Interactive.Container>
    <span className="interactive-foreground">Selected item</span>
  </Interactive.Container>
</Interactive.Stateful>
```
