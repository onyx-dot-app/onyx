# Spacer

**Import:** `import { Spacer } from "@opal/components";`

A zero-content element that inserts a fixed-size gap.
Defaults to vertical spacing of 1rem. Use `orientation` to choose the axis.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `orientation` | `"vertical" \| "horizontal"` | `"vertical"` | Axis of the gap |
| `rem` | `number` | `1` | Size in rem |

## Usage

```tsx
// 2rem vertical gap (most common)
<Spacer rem={2} />

// 1.5rem horizontal gap
<Spacer orientation="horizontal" rem={1.5} />

// Default: 1rem vertical
<Spacer />
```
