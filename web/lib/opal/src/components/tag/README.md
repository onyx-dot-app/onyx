# Tag

**Import:** `import { Tag, TAG_REMOVE_ATTR, type TagProps } from "@opal/components";`

A gray, 1.5rem-tall `Interactive` pill around a `Content` (`secondary` preset): a tag-field value, a filter toggle or a popover trigger. For a coloured label, use [`Badge`](../badge/README.md).

- **Static** (no `onClick` or `onRemove`): the tag look without the hover, such as a tag field's locked tag.
- **Removable** (`onRemove`): a remove `Button` after the title, marked with `TAG_REMOVE_ATTR` for tag-field keyboard flows. Tag fields select a tag by focusing its remove button: the tag turns into a dark pill with an outer ring (Figma State=Focus). Removable titles are always capped.
- **Clickable** (`onClick`): a button (`Interactive.Stateless`, default + secondary). As a popover or dropdown trigger (`aria-haspopup`) it shows the hover look while open, as `Button` does. With `aria-pressed` it is a filter toggle (`Interactive.Stateful`, `select-filter`), inverted while pressed.

`onClick` and `onRemove` cannot be combined. A disabled tag is wrapped in `Disabled`: it dims as a whole, hides its remove button, and its `tooltip` shows the reason.

## Props

| Prop               | Type                                   | Default        | Description                                                                 |
| ------------------ | -------------------------------------- | -------------- | --------------------------------------------------------------------------- |
| `title`            | `string \| RichStr`                    | **(required)** | Tag label text                                                             |
| `icon`             | `IconFunctionComponent`                | —              | Optional icon before the title                                              |
| `iconColor`        | `StatusColor`                         | —              | Icon colour when it is not the tag's gray, kept in every state             |
| `onClick`          | `MouseEventHandler<HTMLButtonElement>` | —              | Makes the tag a button. `ref` is then a `Ref<HTMLButtonElement>`           |
| `onRemove`         | `() => void`                           | —              | Renders the remove button                                                   |
| `removeInTabOrder` | `boolean`                              | `true`         | Removable only: whether the remove button is a Tab stop                     |
| `disabled`         | `boolean`                              | `false`        | Static and removable: dims the tag and hides the remove button             |
| `truncate`         | `boolean`                              | `false`        | Cap the title at 160px with an ellipsis; a cut title shows in full on hover |
| `tooltip`          | `string`                               | —              | Hover tooltip; on a disabled tag, the reason                               |
| `error`            | `boolean`                              | `false`        | Warning icon after the title, for a value the field rejects                 |

## Usage

```tsx
import { Tag } from "@opal/components";
import { SvgAlertTriangle, SvgUsers } from "@opal/icons";

<Tag icon={SvgUsers} title="engineering" onRemove={() => removeGroup(id)} />

<Tag
  icon={SvgAlertTriangle}
  iconColor="warning"
  title="3 failed"
  onClick={openDetails}
/>

<Tag title="Failed" aria-pressed={selected} onClick={toggle} />
```
