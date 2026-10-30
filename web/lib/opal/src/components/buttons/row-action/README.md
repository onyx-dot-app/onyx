# RowAction

**Import:** `import { RowAction, type RowActionProps } from "@opal/components";`

The value or action at the end of a row: icon and title on the left, a `rightIcon` or `chevron` at the right edge. Built on `Interactive.Stateless` > `Interactive.Container` with the `internal` prominence and the `lg` size: no border, transparent at rest. Every mode renders the same box, so a column of `RowAction`s lines up: icons start at the same x, and right icons and chevrons end at the same x.

## Modes

The props decide the mode; there is no mode prop.

- **Button** — pass `onClick`. A `<button>` with hover, keyboard focus (painted as hover) and pressed states.
- **Dropdown trigger** — wrap it in `Dropdown.Trigger asChild` (which passes `onClick`) and pass `chevron`. While the list is open it keeps the hover look and the chevron rotates.
- **Link** — pass `href` (+ `target`).
- **Static** — pass neither. Same box and colors, but no hover, role or tab stop: a value that cannot be changed.

## Props

| Prop          | Type                                | Default     | Description                                                |
| ------------- | ----------------------------------- | ----------- | ---------------------------------------------------------- |
| `children`    | `string \| RichStr`                 | —           | Title                                                      |
| `icon`        | `IconFunctionComponent`             | —           | Icon before the title                                      |
| `rightIcon`   | `IconFunctionComponent`             | —           | Icon at the right edge. Not with `chevron`                 |
| `chevron`     | `boolean`                           | `false`     | A chevron at the right edge that rotates while open        |
| `variant`     | `"default" \| "action" \| "danger"` | `"default"` | Color variant                                              |
| `width`       | `"fit" \| "full" \| Spacing`        | `"full"`    | A number is a fixed length as a spacing step (`N / 4` rem) |
| `onClick`     | `MouseEventHandler`                 | —           | Makes it a button                                          |
| `href`        | `string`                            | —           | Makes it a link                                            |
| `tooltip`     | `string`                            | —           | Tooltip text                                               |
| `tooltipSide` | `TooltipSide`                       | `"top"`     | Tooltip placement                                          |
| `disabled`    | `boolean`                           | `false`     | Disables the button                                        |

## Usage

```tsx
import { Dropdown, RowAction } from "@opal/components";
import { SvgArrowExchange, SvgBubbleText, SvgEdit, SvgUserManage } from "@opal/icons";

// Button: opens another view
<RowAction icon={SvgUserManage} rightIcon={SvgArrowExchange} tooltip="Transfer Ownership" onClick={openTransfer}>
  Owner
</RowAction>

// Dropdown trigger
<Dropdown>
  <Dropdown.Trigger asChild>
    <RowAction icon={SvgBubbleText} chevron>
      View & Chat
    </RowAction>
  </Dropdown.Trigger>
  <Dropdown.Data items={items} />
</Dropdown>

// Static
<RowAction icon={SvgEdit}>Edit</RowAction>
```
