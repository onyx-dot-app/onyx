# IconTooltip

**Import:** `import { IconTooltip } from "@opal/components";`

A small icon that explains something in a tooltip, such as how to fix a failed
check. It is not interactive: no click and no hover style, only a help cursor.
It takes keyboard focus, so the tooltip opens on focus as well as on hover.

## Props

| Prop         | Type                    | Default              | Description                                                           |
| ------------ | ----------------------- | -------------------- | --------------------------------------------------------------------- |
| `icon`       | `IconFunctionComponent` | `SvgInfo`            | Shown at 1rem with 0.125rem padding (1.25rem)                         |
| `status`     | `IconTooltipStatus`     | `"default"`          | Colours the icon's stroke                                             |
| `tooltip`    | `string \| RichStr`     | —                    | Opens above the icon, at its start; without it only the icon shows    |
| `aria-label` | `string`                | `"More information"` | The icon's name for assistive tech (translated through `OpalStrings`) |

`IconTooltipStatus = Extract<StatusVariants, "default" | "info" | "success" | "warning" | "error">`.

| Status    | Stroke              |
| --------- | ------------------- |
| `default` | `text-03`           |
| `info`    | `status-info-05`    |
| `success` | `status-success-05` |
| `warning` | `theme-amber-05`    |
| `error`   | `status-error-05`   |

## Usage

```tsx
<IconTooltip status="error" tooltip="Add the read:space scope, then re-run." />
```
