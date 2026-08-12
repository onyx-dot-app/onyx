# Section

**Import:** `import { Section } from "@opal/layouts";`

A flexbox container primitive for grouping related content. Configurable direction, alignment,
spacing, and dimensions. Defaults to a full-width / full-height column with centered children
and a gap of `4` (1rem).

`gap` and `padding` are spacing steps, not raw lengths: `N` is `N / 4` rem, the same scale
Tailwind uses. So `gap={2}` is the same distance as `gap-2`.

## Props

| Prop             | Type                                        | Default    | Description                  |
| ---------------- | ------------------------------------------- | ---------- | ---------------------------- |
| `flexDirection`  | `"row" \| "column"`                         | `"column"` | Flex direction               |
| `justifyContent` | `"start" \| "center" \| "end" \| "between"` | `"center"` | Main-axis justification      |
| `alignItems`     | `"start" \| "center" \| "end" \| "stretch"` | `"center"` | Cross-axis alignment         |
| `width`          | `"auto" \| "fit" \| "full" \| number`       | `"full"`   | Width. `number` = rem.       |
| `height`         | `"auto" \| "fit" \| "full" \| number`       | `"full"`   | Height. `number` = rem.      |
| `gap`            | `Spacing`                                   | `4`        | Gap between children, as a spacing step (`N / 4` rem) |
| `padding`        | `Spacing`                                   | `0`        | Padding, as a spacing step (`N / 4` rem)              |
| `wrap`           | `boolean`                                   | `false`    | Enables `flex-wrap`          |
| `dbg`            | `boolean`                                   | `false`    | Adds a red debug border      |
| `className`      | `string`                                    | —          | Additional classes           |
| `ref`            | `Ref<HTMLDivElement>`                       | —          | Forwarded ref                |

## Usage

```tsx
import { Section } from "@opal/layouts";

// Column with default gap
<Section>
  <Card>First</Card>
  <Card>Second</Card>
</Section>

// Row, items aligned to start
<Section flexDirection="row" justifyContent="start" alignItems="center">
  <Button>Cancel</Button>
  <Button>Save</Button>
</Section>

// Tighter gap, custom width
<Section gap={2} width="fit">
  <Tag>One</Tag>
  <Tag>Two</Tag>
</Section>
```

## Notes

- `<Disabled>` from `@opal/core` uses `display: contents` and can wrap a `Section` without
  affecting layout.
- Children stretch by default (`alignItems="center"` on the cross axis but `width="full"` on
  the wrapper). Override with `alignItems="stretch"` for typical form layouts.
