# EmptyMessageCard

**Import:** `import { EmptyMessageCard, type EmptyMessageCardProps } from "@opal/components";`

A pre-configured Card for empty states. Renders a transparent card with a dashed border containing a muted icon and message text using the `Content` layout.

## Props

### Base props (all presets)

| Prop         | Type                          | Default       | Description                        |
| ------------ | ----------------------------- | ------------- | ---------------------------------- |
| `sizePreset` | `"secondary" \| "main-ui"`   | `"secondary"` | Controls layout and text sizing    |
| `icon`       | `IconFunctionComponent`       | `SvgEmpty`    | Icon displayed alongside the title |
| `title`      | `string \| RichStr`           | —             | Primary message text (required)    |
| `padding`    | `PaddingVariants`             | `"md"`        | Padding preset for the card        |
| `ref`        | `React.Ref<HTMLDivElement>`   | —             | Ref forwarded to the root div      |

### `sizePreset="main-ui"` only

| Prop          | Type                | Default | Description              |
| ------------- | ------------------- | ------- | ------------------------ |
| `description` | `string \| RichStr` | —       | Optional description text |

> `description` is **not accepted** when `sizePreset` is `"secondary"` (the default).

## Usage

```tsx
import { EmptyMessageCard } from "@opal/components";
import { SvgSparkle, SvgFileText, SvgActions } from "@opal/icons";

// Default empty state (secondary)
<EmptyMessageCard title="No items yet." />

// With custom icon
<EmptyMessageCard icon={SvgSparkle} title="No agents selected." />

// main-ui with description
<EmptyMessageCard
  sizePreset="main-ui"
  icon={SvgActions}
  title="No Actions Found"
  description="Provide OpenAPI schema to preview actions here."
/>

// Custom padding
<EmptyMessageCard padding="xs" icon={SvgFileText} title="No documents available." />
```
