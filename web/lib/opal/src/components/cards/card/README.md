# Card

**Import:** `import { Card, type CardProps } from "@opal/components";`

A plain container component with configurable background, border, padding, and rounding. Uses a simple `<div>` internally with `overflow-clip`.

## Architecture

The `sizeVariant` controls both padding and border-radius, mirroring the same mapping used by `Button` and `Interactive.Container`:

| Size      | Padding | Rounding       |
|-----------|---------|----------------|
| `lg`      | `p-2`   | `rounded-12`   |
| `md`      | `p-1`   | `rounded-08`   |
| `sm`      | `p-1`   | `rounded-08`   |
| `xs`      | `p-0.5` | `rounded-04`   |
| `2xs`     | `p-0.5` | `rounded-04`   |
| `fit`     | `p-0`   | `rounded-12`   |

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `sizeVariant` | `SizeVariant` | `"lg"` | Controls padding and border-radius |
| `backgroundVariant` | `"none" \| "light" \| "heavy"` | `"light"` | Background fill intensity |
| `borderVariant` | `"none" \| "dashed" \| "solid"` | `"none"` | Border style |
| `ref` | `React.Ref<HTMLDivElement>` | — | Ref forwarded to the root div |
| `children` | `React.ReactNode` | — | Card content |

## Background Variants

- **`none`** — Transparent background. Use for seamless inline content.
- **`light`** — Subtle tinted background (`bg-background-tint-00`). The default, suitable for most cards.
- **`heavy`** — Stronger tinted background (`bg-background-tint-01`). Use for emphasis or nested cards that need visual separation.

## Border Variants

- **`none`** — No border. Use when cards are visually grouped or in tight layouts.
- **`dashed`** — Dashed border. Use for placeholder or empty states.
- **`solid`** — Solid border. Use for prominent, standalone cards.

## Usage

```tsx
import { Card } from "@opal/components";

// Default card (light background, no border, lg padding + rounding)
<Card>
  <h2>Card Title</h2>
  <p>Card content</p>
</Card>

// Compact card with solid border
<Card borderVariant="solid" sizeVariant="sm">
  <p>Compact card</p>
</Card>

// Empty state card
<Card backgroundVariant="none" borderVariant="dashed">
  <p>No items yet</p>
</Card>

// Heavy background, tight padding
<Card backgroundVariant="heavy" sizeVariant="xs">
  <p>Highlighted content</p>
</Card>
```
