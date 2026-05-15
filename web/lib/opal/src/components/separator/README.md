# Separator

**Import:** `import { Separator } from "@opal/components";`

A visual divider that separates content horizontally or vertically. Built on Radix Separator
primitives.

## Props

| Prop          | Type                         | Default        | Description                                                |
| ------------- | ---------------------------- | -------------- | ---------------------------------------------------------- |
| `orientation` | `"horizontal" \| "vertical"` | `"horizontal"` | Direction of the line                                      |
| `decorative`  | `boolean`                    | `true`         | When `false`, the separator is announced by screen readers |
| `noPadding`   | `boolean`                    | `false`        | Removes the default padding around the line                |
| `paddingXRem` | `number`                     | —              | Custom horizontal padding in rem (overrides default)       |
| `paddingYRem` | `number`                     | —              | Custom vertical padding in rem (overrides default)         |
| `className`   | `string`                     | —              | Additional classes for the wrapper                         |

## Usage

```tsx
import { Separator } from "@opal/components";

// Horizontal (default)
<Separator />

// Vertical
<Separator orientation="vertical" />

// Custom padding
<Separator paddingYRem={0.5} />

// No padding
<Separator noPadding />
```
