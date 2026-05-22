# Spacer

**Import:** `import { Spacer } from "@opal/components";`

A zero-content element that inserts a fixed-size vertical or horizontal gap.
Prefers `rem` units by default; use `pixels` for pixel-perfect sizing.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `vertical` | `boolean` | `true` | Insert vertical (height) space |
| `horizontal` | `boolean` | — | Insert horizontal (width) space |
| `rem` | `number` | `1` | Size in rem (mutually exclusive with `pixels`) |
| `pixels` | `number` | — | Size in pixels (mutually exclusive with `rem`) |

## Usage

```tsx
// 2rem vertical gap (most common)
<Spacer vertical rem={2} />

// 8px horizontal gap
<Spacer horizontal pixels={8} />

// Default: 1rem vertical
<Spacer />
```
