# Badge

**Import:** `import { Badge, type BadgeProps } from "@opal/components";`

A small coloured label for status, category or metadata: an icon and a title in a tinted pill, drawn by a `Content`. It does nothing on click. `size` is the height on the Tailwind scale: `4` is 1rem (a `figure-small-value` title, 2px padding, 4px corners), `5` is 1.25rem (a `secondary-body` title, 2px padding, 4px corners), `6` is 1.5rem (a `secondary-body` title, 4px padding, 8px corners).

For a removable, clickable or tag-field pill, use [`Tag`](../tag/README.md). For a hover tooltip, pass `tooltip`; do not wrap the badge in `Tooltip`, which nests inside the title's own tooltip. `Badge` takes no DOM attributes, but its ref and the props a wrapping popover trigger injects still reach its root.

`color` sets the tinted background, and the label and icon colours (`Content`'s status colours, see
the [Content README](../../layouts/content/README.md#colours)). `titleColor` overrides the label, as on
`Content`: the icon keeps `color`'s, except on `default`, where it follows the label.

## Props

| Prop      | Type                               | Default        | Description                    |
| --------- | ---------------------------------- | -------------- | ------------------------------ |
| `title`   | `string \| RichStr`                | **(required)** | Badge label text               |
| `icon`    | `IconFunctionComponent`            | —              | Optional icon before the title |
| `color`   | `StatusColor`                   | `"default"`    | Status color                   |
| `titleColor` | `Exclude<TextColor, "inherit">` | per `color` | Overrides the label colour, as on `Content` |
| `size`    | `4 \| 5 \| 6`                      | `4`            | Height on the Tailwind scale   |
| `tooltip` | `string \| RichStr`                | —              | Shown on every hover. Replaces the full-title tooltip, so a cut title shows only this |

### `color`

`StatusColor` from `@opal/types`. The fill is the badge's (`BADGE_COLORS`); the text and icon colours
are `Content`'s (see the [Content README](../../layouts/content/README.md#colours)). A `default` badge
mutes its text and icon to `text-03` on its gray fill.

| Color     | Fill                 |
| --------- | -------------------- |
| `default` | `background-tint-02` |
| `info`    | `theme-blue-01`      |
| `success` | `theme-green-01`     |
| `warning` | `status-warning-01`  |
| `pending` | `theme-amber-01`     |
| `queued`  | `theme-purple-01`    |
| `error`   | `status-error-01`    |

## Usage

```tsx
import { Badge } from "@opal/components";
import { SvgAlertTriangle, SvgRefreshCw } from "@opal/icons";

<Badge title="Beta" color="info" />

<Badge icon={SvgRefreshCw} title="Indexing" color="info" titleColor="text-04" size={6} />

<Badge icon={SvgAlertTriangle} title="3" color="warning" titleColor="text-04" tooltip="3 warnings" />
```
