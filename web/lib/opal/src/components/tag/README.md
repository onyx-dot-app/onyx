# Tag

**Import:** `import { Tag, type TagProps } from "@opal/components";`

A small coloured label for status, category or metadata: an icon and a title in a tinted pill, drawn by a `Content` (`secondary` preset, `body` variant, so the title is `secondary-body`). It does nothing on click. 1rem tall at `sm`, 1.375rem at `md`.

For a removable, clickable or chip-field pill, use [`Chip`](../chip/README.md). For a hover tooltip, wrap the tag in `Tooltip`. `Tag` takes no DOM attributes, but its ref and the props a wrapping `Tooltip` or popover trigger injects still reach its root.

| Variant   | Background        | Icon             | Label            | Use                                     |
| --------- | ----------------- | ---------------- | ---------------- | --------------------------------------- |
| `default` | the color's `-01` | the color's text | the color's text | Category and metadata labels            |
| `status`  | the color's `-01` | the color's text | `text-04`        | Status pills (Indexing, Paused, Failed) |
| `count`   | none              | the color's text | `text-04`        | Warning and failure counts in rows      |

## Props

| Prop      | Type                               | Default        | Description                     |
| --------- | ---------------------------------- | -------------- | ------------------------------- |
| `title`   | `string \| RichStr`                | **(required)** | Tag label text                  |
| `icon`    | `IconFunctionComponent`            | —              | Optional icon before the title  |
| `color`   | `TagColor`                         | `"gray"`       | Color variant                   |
| `variant` | `"default" \| "status" \| "count"` | `"default"`    | How the color is applied        |
| `size`    | `"sm" \| "md"`                     | `"sm"`         | Size (Figma Small / Regular)    |

### `TagColor`

`"green" | "blue" | "purple" | "amber" | "orange" | "red" | "gray" | "white"`

| Color    | Background           | Text                                  |
| -------- | -------------------- | ------------------------------------- |
| `green`  | `theme-green-01`     | `theme-green-05`                      |
| `blue`   | `theme-blue-01`      | `theme-blue-05`                       |
| `purple` | `theme-purple-01`    | `theme-purple-05`                     |
| `amber`  | `theme-amber-01`     | `theme-amber-05`                      |
| `orange` | `status-warning-01`  | `status-warning-05`                   |
| `red`    | `status-error-01`    | `status-error-05`                     |
| `gray`   | `background-tint-02` | `text-03`                             |
| `white`  | `background-tint-00` | `text-04`, for a pill on a tinted row |

## Usage

```tsx
import { Tag, Tooltip } from "@opal/components";
import { SvgAlertTriangle, SvgRefreshCw } from "@opal/icons";

<Tag title="Beta" color="blue" />

<Tag icon={SvgRefreshCw} title="Indexing" color="blue" variant="status" size="md" />

<Tooltip tooltip="3 warnings" side="top">
  <Tag icon={SvgAlertTriangle} title="3" color="orange" variant="count" />
</Tooltip>
```
