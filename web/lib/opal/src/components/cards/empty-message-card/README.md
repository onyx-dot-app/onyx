# EmptyMessageCard

**Import:** `import { EmptyMessageCard, type EmptyMessageCardProps } from "@opal/components";`

A pre-configured Card for empty states. Renders a transparent card with a dashed border containing a muted icon and message text using the `Content` layout.

## Props

| Prop      | Type                        | Default    | Description                      |
| --------- | --------------------------- | ---------- | -------------------------------- |
| `icon`    | `IconFunctionComponent`     | `SvgEmpty` | Icon displayed alongside the title |
| `title`   | `string`                    | —          | Primary message text (required)  |
| `padding` | `PaddingVariants`           | `"sm"`     | Padding preset for the card      |
| `ref`     | `React.Ref<HTMLDivElement>` | —          | Ref forwarded to the root div    |

## Usage

```tsx
import { EmptyMessageCard } from "@opal/components";
import { SvgSparkle, SvgFileText } from "@opal/icons";

// Default empty state
<EmptyMessageCard title="No items yet." />

// With custom icon
<EmptyMessageCard icon={SvgSparkle} title="No agents selected." />

// With custom padding
<EmptyMessageCard padding="xs" icon={SvgFileText} title="No documents available." />
```
