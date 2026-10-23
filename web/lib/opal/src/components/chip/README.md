# Chip

**Import:** `import { Chip, CHIP_REMOVE_ATTR, type ChipProps } from "@opal/components";`

A gray, 1.375rem-tall `Interactive` pill around a `Content` (`secondary` preset): a chip-field value, a filter toggle or a popover trigger. For a coloured label that does nothing on click, use [`Tag`](../tag/README.md).

- **Static** (no `onClick` or `onRemove`): the chip look without the hover, such as a chip field's locked chip.
- **Removable** (`onRemove`): a remove `Button` after the title, marked with `CHIP_REMOVE_ATTR` for chip-field keyboard flows. Chip fields select a chip by focusing its remove button: the chip turns into a dark pill with an outer ring (Figma State=Focus). Removable titles are always capped.
- **Clickable** (`onClick`): a button (`Interactive.Stateless`, default + secondary). As a popover or dropdown trigger (`aria-haspopup`) it shows the hover look while open, as `Button` does. With `aria-pressed` it is a filter toggle (`Interactive.Stateful`, `select-filter`), inverted while pressed.

`onClick` and `onRemove` cannot be combined. A disabled chip is wrapped in `Disabled`: it dims as a whole, hides its remove button, and its `tooltip` shows the reason.

## Props

| Prop               | Type                                   | Default        | Description                                                                 |
| ------------------ | -------------------------------------- | -------------- | --------------------------------------------------------------------------- |
| `title`            | `string \| RichStr`                    | **(required)** | Chip label text                                                             |
| `icon`             | `IconFunctionComponent`                | —              | Optional icon before the title                                              |
| `iconColor`        | `TagColor`                             | —              | Icon colour when it is not the chip's gray, kept in every state             |
| `onClick`          | `MouseEventHandler<HTMLButtonElement>` | —              | Makes the chip a button. `ref` is then a `Ref<HTMLButtonElement>`           |
| `onRemove`         | `() => void`                           | —              | Renders the remove button                                                   |
| `removeInTabOrder` | `boolean`                              | `true`         | Removable only: whether the remove button is a Tab stop                     |
| `disabled`         | `boolean`                              | `false`        | Static and removable: dims the chip and hides the remove button             |
| `truncate`         | `boolean`                              | `false`        | Cap the title at 160px with an ellipsis; a cut title shows in full on hover |
| `tooltip`          | `string`                               | —              | Hover tooltip; on a disabled chip, the reason                               |
| `error`            | `boolean`                              | `false`        | Warning icon after the title, for a value the field rejects                 |

## Usage

```tsx
import { Chip } from "@opal/components";
import { SvgAlertTriangle, SvgUsers } from "@opal/icons";

<Chip icon={SvgUsers} title="engineering" onRemove={() => removeGroup(id)} />

<Chip
  icon={SvgAlertTriangle}
  iconColor="orange"
  title="3 failed"
  onClick={openDetails}
/>

<Chip title="Failed" aria-pressed={selected} onClick={toggle} />
```
