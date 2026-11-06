# BadgeButton

**Import:** `import { BadgeButton, type BadgeButtonProps } from "@opal/components";`

A [`Badge`](../badge/README.md) made clickable by an `Interactive` wrapper. With `onClick` alone it is a button, named by its `tooltip`, which is also its hover text. With `pressed` it is a filter toggle (`aria-pressed`): the pressed badge shows its title in its own colour, since the badge covers the selected surface behind it. The focus ring follows the pill's corners. The badge itself stays static, so for a label that does nothing on click use `Badge`, and for a gray or removable pill use [`Tag`](../tag/README.md).

## Props

Every `Badge` prop except `ref`, plus:

| Prop      | Type         | Default | Description                                  |
| --------- | ------------ | ------- | -------------------------------------------- |
| `onClick` | `() => void` | —       | The click                                    |
| `tooltip` | `string`     | —       | Hover text and the button's accessible name |
| `pressed` | `boolean`    | —       | Set for a filter toggle                      |

## Usage

```tsx
import { BadgeButton } from "@opal/components";
import { SvgAlertTriangle, SvgXOctagon } from "@opal/icons";

<BadgeButton icon={SvgAlertTriangle} title="3" color="warning" titleColor="text-04" tooltip="View Errors" onClick={openErrors} />

<BadgeButton icon={SvgXOctagon} title="4" color="error" titleColor="text-04" size={6} tooltip="4 failed" pressed={failedOnly} onClick={toggleFailed} />
```
