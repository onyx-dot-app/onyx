# Badge

**Import:** `import { Badge, type BadgeProps, type BadgeButtonProps } from "@opal/components";`

A small coloured label for status, category or metadata: an icon and a title in a tinted pill, drawn by a `Content` (`secondary` preset, `body` variant, so the title is `secondary-body`). With `onClick` it is a button named by its `tooltip`, and with `aria-pressed` a filter toggle that rings itself in its colour while pressed. `size` is the height on the Tailwind scale: `4` is 1rem (2px inline padding, 4px corners), `5` is 1.25rem (2px padding, 4px corners), `6` is 1.5rem (4px padding, 8px corners).

For a gray, removable or tag-field pill, use [`Tag`](../tag/README.md). For a hover tooltip on a static badge, wrap it in `Tooltip`. `Badge` takes no DOM attributes, but its ref and the props a wrapping `Tooltip` or popover trigger injects still reach its root. On a clickable badge the ref is the pill inside the button, and the focus ring follows the corners.

`color` sets the tinted background and the icon. `textColor` sets the label: `"inherit"` (the default)
is the text colour matched to the background, and any other `TextColor` (`"text-04"` for a status
pill) is that colour.

## Props

| Prop      | Type                               | Default        | Description                    |
| --------- | ---------------------------------- | -------------- | ------------------------------ |
| `title`   | `string \| RichStr`                | **(required)** | Badge label text               |
| `icon`    | `IconFunctionComponent`            | —              | Optional icon before the title |
| `color`   | `StatusVariants`                   | `"default"`    | Status color                   |
| `textColor` | `TextColor`                      | `"inherit"`    | Label colour; `"inherit"` matches `color` |
| `size`    | `4 \| 5 \| 6`                      | `4`            | Height on the Tailwind scale   |
| `onClick` | `() => void`                       | —              | Makes the badge a button       |
| `tooltip` | `string`                           | —              | With `onClick`: tooltip and name |
| `aria-pressed` | `boolean`                     | —              | With `onClick`: a filter toggle |

### `color`

`StatusVariants` from `@opal/types`:

| Color     | Background           | Text                |
| --------- | -------------------- | ------------------- |
| `default` | `background-tint-02` | `text-03`           |
| `info`    | `theme-blue-01`      | `theme-blue-05`     |
| `success` | `theme-green-01`     | `theme-green-05`    |
| `warning` | `status-warning-01`  | `status-warning-05` |
| `pending` | `theme-amber-01`     | `theme-amber-05`    |
| `queued`  | `theme-purple-01`    | `theme-purple-05`   |
| `error`   | `status-error-01`    | `status-error-05`   |

## Usage

```tsx
import { Badge, Tooltip } from "@opal/components";
import { SvgAlertTriangle, SvgRefreshCw, SvgXOctagon } from "@opal/icons";

<Badge title="Beta" color="info" />

<Badge icon={SvgRefreshCw} title="Indexing" color="info" textColor="text-04" size={6} />

<Tooltip tooltip="3 warnings" side="top">
  <Badge icon={SvgAlertTriangle} title="3" color="warning" textColor="text-04" />
</Tooltip>

<Badge icon={SvgAlertTriangle} title="3" color="warning" textColor="text-04" tooltip="View Errors" onClick={openErrors} />

<Badge icon={SvgXOctagon} title="4" color="error" textColor="text-04" size={6} tooltip="4 failed" aria-pressed={failedOnly} onClick={toggleFailed} />
```
