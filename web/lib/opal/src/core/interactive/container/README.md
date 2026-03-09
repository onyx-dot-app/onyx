# Interactive.Container

**Import:** `import { Interactive } from "@opal/core";` — use as `Interactive.Container`.

Structural container shared by both `Interactive.Stateless` and `Interactive.Stateful`. Provides consistent height, rounding, padding, and optional border. Renders a `<div>` by default, or a `<button>` when `type` is provided.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `heightVariant` | `SizeVariant` | `"lg"` | Height preset (`2xs`–`lg`, `fit`) |
| `roundingVariant` | `"default" \| "compact" \| "mini"` | `"default"` | Border-radius preset |
| `widthVariant` | `WidthVariant` | — | Width preset (`"auto"`, `"fit"`, `"full"`) |
| `border` | `boolean` | `false` | Renders a 1px border |
| `type` | `"submit" \| "button" \| "reset"` | — | When set, renders a `<button>` element |

## Usage

```tsx
<Interactive.Stateless variant="default" prominence="primary">
  <Interactive.Container heightVariant="sm" roundingVariant="compact" border>
    <span>Content</span>
  </Interactive.Container>
</Interactive.Stateless>
```
