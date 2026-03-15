# Interactive.Stateless

**Import:** `import { Interactive } from "@opal/core";` — use as `Interactive.Stateless`.

Stateless interactive surface primitive for buttons, links, and cards. Applies variant/prominence color styling via CSS data-attributes and merges onto a single child element via Radix `Slot`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"none" \| "default" \| "action" \| "danger"` | `"default"` | Color variant |
| `prominence` | `"primary" \| "secondary" \| "tertiary" \| "internal"` | `"primary"` | Color prominence within the variant |
| `interaction` | `"rest" \| "hover" \| "active"` | `"rest"` | JS-controlled interaction override |
| `group` | `string` | — | Tailwind group class for `group-hover:*` |
| `disabled` | `boolean` | `false` | Disables the element |
| `href` | `string` | — | URL for link behavior |
| `target` | `string` | — | Link target (e.g. `"_blank"`) |

## CSS custom properties

Sets `--interactive-foreground` and `--interactive-foreground-icon` per variant/prominence/state. Descendants opt in via:
- `.interactive-foreground` — text color
- `.interactive-foreground-icon` — icon color

## Usage

```tsx
<Interactive.Stateless variant="default" prominence="primary" onClick={handleClick}>
  <Interactive.Container border>
    <span className="interactive-foreground">Click me</span>
  </Interactive.Container>
</Interactive.Stateless>
```
