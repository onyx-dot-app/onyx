# Animations (Hoverable)

**Import:** `import { Hoverable } from "@opal/core";`

Provides coordinated hover-state animations across a group of elements. A `Hoverable.Root` tracks hover state and broadcasts it to `Hoverable.Item` descendants via a per-group React context.

## Sub-components

| Sub-component | Role |
|---|---|
| `Hoverable.Root` | Wraps a group of items. Tracks mouse enter/leave and provides hover state via context. |
| `Hoverable.Item` | Reads hover state from its group's context. Applies a CSS class (`opal-hoverable-item`) with variant-specific transitions (e.g. opacity, scale). |

## Props

### Hoverable.Root

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `group` | `string` | `"default"` | Named group for independent hover tracking |

### Hoverable.Item

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `group` | `string` | `"default"` | Which group to listen to |
| `variant` | `HoverableItemVariant` | `"fade"` | Animation variant |

## Usage

```tsx
import { Hoverable } from "@opal/core";

<Hoverable.Root group="card">
  <div>
    <Hoverable.Item group="card" variant="fade">
      <span>Appears on hover</span>
    </Hoverable.Item>
  </div>
</Hoverable.Root>
```
