# Interactive.Stateful

**Import:** `import { Interactive } from "@opal/core";` — use as `Interactive.Stateful`.

Stateful interactive surface primitive for elements that maintain a value state (empty/filled/selected). Used for toggles, sidebar items, and selectable list rows. Applies variant/state color styling via CSS data-attributes and merges onto a single child element via Radix `Slot`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"select-light" \| "select-heavy" \| "select-tinted" \| "select-filter" \| "sidebar"` | `"select-heavy"` | Color variant |
| `state` | `"empty" \| "filled" \| "selected"` | `"empty"` | Current value state |
| `interaction` | `"rest" \| "hover" \| "active"` | `"rest"` | JS-controlled interaction override |
| `group` | `string` | — | Tailwind group class for `group-hover:*` |
| `disabled` | `boolean` | `false` | Disables the element |
| `href` | `string` | — | URL for link behavior |
| `target` | `string` | — | Link target (e.g. `"_blank"`) |

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
