# Hoverable

**Import:** `import { Hoverable } from "@opal/core";`

A compound component for hover-to-reveal patterns. Provides context-based group hover detection as well as local CSS `:hover` mode.

## Sub-components

| Sub-component | Role |
|---|---|
| `Hoverable.Root` | Container that tracks hover state for a named group and provides it via React context. |
| `Hoverable.Item` | Element whose visibility is controlled by hover state. Supports local (CSS `:hover`) and group (context-driven) modes. |

## Hoverable.Root Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `group` | `string` | **(required)** | Named group key. Must match the `group` on corresponding `Hoverable.Item`s. |
| `widthVariant` | `WidthVariant` | `"auto"` | Width preset for the root `<div>`. `"auto"` or `"full"`. |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root `<div>`. |
| _...and all `HTMLAttributes<HTMLDivElement>`_ | | | `onMouseEnter`, `onMouseLeave`, etc. (merged with internal handlers) |

## Hoverable.Item Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `group` | `string` | — | When provided, reads hover state from the nearest matching `Hoverable.Root`. When omitted, uses local CSS `:hover`. |
| `variant` | `"opacity-on-hover"` | `"opacity-on-hover"` | The hover-reveal effect to apply. |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the item `<div>`. |
| _...and all `HTMLAttributes<HTMLDivElement>`_ | | | |

## Usage

```tsx
import { Hoverable } from "@opal/core";

// Group mode — hovering the card reveals the trash icon
<Hoverable.Root group="card" widthVariant="full">
  <Card>
    <span>Card content</span>
    <Hoverable.Item group="card" variant="opacity-on-hover">
      <TrashIcon />
    </Hoverable.Item>
  </Card>
</Hoverable.Root>

// Local mode — hovering the item itself reveals it
<Hoverable.Item variant="opacity-on-hover">
  <TrashIcon />
</Hoverable.Item>
```

## Error handling

If `group` is specified on a `Hoverable.Item` but no matching `Hoverable.Root` ancestor exists, the component throws an error at render time.
