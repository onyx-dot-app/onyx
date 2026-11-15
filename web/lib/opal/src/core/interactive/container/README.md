# Interactive.Container

**Import:** `import { Interactive } from "@opal/core";` — use as `Interactive.Container`.

Structural container shared by both `Interactive.Stateless` and `Interactive.Stateful`. Provides consistent height, rounding, padding, and optional border. Renders a `<div>` by default, or a `<button>` when `type` is provided.

## Props

| Prop       | Type                              | Default | Description                                      |
| ---------- | --------------------------------- | ------- | ------------------------------------------------ |
| `size`     | `SizeVariant`                     | `"lg"`  | Height preset (`2xs`–`lg`, `fit`)                |
| `rounding` | `Rounding`                        | `3`     | Corner radius, `N / 4` rem (`0.5`–`5`, `"full"`) |
| `width`    | `WidthVariant`                    | —       | Width preset (`"auto"`, `"fit"`, `"full"`)       |
| `border`   | `boolean`                         | `false` | Renders a 1px border                             |
| `type`     | `"submit" \| "button" \| "reset"` | —       | When set, renders a `<button>` element           |

## Usage

```tsx
<Interactive.Stateless variant="default" prominence="primary">
  <Interactive.Container size="sm" rounding={2} border>
    <span>Content</span>
  </Interactive.Container>
</Interactive.Stateless>
```
