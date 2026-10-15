# Tag

**Import:** `import { Tag, type TagProps } from "@opal/components";`

A small colored label used to annotate items with status, category, or metadata. Two types, matching the Figma `Tag` component:

- **Passive** (default): metadata label. 1rem tall with `font-figure-small-value` at `sm`, 1.375rem with `secondary-body` at `md`.
- **Toggle** (`onClick` set, no `onRemove`): the passive tag as a button, with an inset ring in its own color on hover and while `selected`. The tooltip is its accessible label. Use it for count tags that filter a list.
- **Editable** (`onRemove` set): remove button, gray hover, and a dark focus-within treatment chip fields use as the keyboard-selection state before deleting a tag.

## Props

| Prop       | Type                    | Default        | Description                                                                                    |
| ---------- | ----------------------- | -------------- | ---------------------------------------------------------------------------------------------- |
| `title`    | `string \| RichStr`     | **(required)** | Tag label text                                                                                 |
| `color`    | `TagColor`              | `"gray"`       | Color variant                                                                                  |
| `icon`     | `IconFunctionComponent` | —              | Optional icon before the title                                                                 |
| `size`     | `"sm" \| "md"`          | `"sm"`         | Size variant (Figma Small / Regular)                                                           |
| `font` | `TextFont` | Size/type default | Override label and value typography to match the surrounding surface |
| `removeInTabOrder` | `boolean` | `true` | Editable only: whether the remove button is a Tab stop. Chip fields set it off and walk chips with the arrows |
| `onRemove` | `() => void`            | —              | Switches to the editable type and renders the remove button                                    |
| `disabled` | `boolean`               | `false`        | Editable only: dims the tag, hides the remove button                                           |
| `value`    | `string \| RichStr`     | —              | Secondary text after the title, in `text-03`                                                   |
| `truncate` | `boolean`               | `false`        | Cap the title at 120px (`sm`) / 160px (`md`) with an ellipsis. Editable tags are always capped |
| `tooltip`  | `string`                | —              | Hover tooltip. Defaults to string titles on editable or truncated tags                         |
| `error`    | `boolean`               | `false`        | Warning indicator after the title (no Figma variant, exists for chip-field validation)         |
| `onClick`  | `() => void`            | —              | Switches to the toggle type. Ignored when `onRemove` is set                                    |
| `selected` | `boolean`               | `false`        | Toggle only: solid ring and `aria-pressed`                                                     |

### `TagColor`

`"green" | "blue" | "purple" | "amber" | "red" | "gray"`

| Color    | Background           | Text                                       |
| -------- | -------------------- | ------------------------------------------ |
| `green`  | `theme-green-01`     | `theme-green-05`                           |
| `blue`   | `theme-blue-01`      | `theme-blue-05`                            |
| `purple` | `theme-purple-01`    | `theme-purple-05`                          |
| `amber`  | `theme-amber-01`     | `theme-amber-05`                           |
| `red`    | `status-error-01`    | `status-error-05`                          |
| `gray`   | `background-tint-02` | `text-03` (passive) / `text-04` (editable) |

## Usage Examples

```tsx
import { Tag } from "@opal/components";
import SvgStar from "@opal/icons/star";

// Basic
<Tag title="New" color="green" />

// With icon
<Tag icon={SvgStar} title="Featured" color="purple" />

// Editable (chip): remove button, hover, focus states
<Tag title="filter:owner" onRemove={() => removeFilter(id)} />

// Editable with secondary value
<Tag title="env" value="production" size="md" onRemove={() => {}} />

// Toggle: a count tag that filters its list
<Tag
  icon={SvgCheckCircle}
  title="12"
  tooltip="12 succeeded"
  color="green"
  selected={group === "succeeded"}
  onClick={() => toggle("succeeded")}
/>

// Truncated passive tag with the default title tooltip
<Tag title="A very long label" truncate />
```

## Usage inside Content

Tag can be rendered as an accessory inside `Content`'s ContentMd via the `tag` prop:

```tsx
import { Content } from "@opal/layouts";
import SvgSearch from "@opal/icons/search";

<Content
  icon={SvgSearch}
  sizePreset="main-ui"
  title="My Item"
  tag={{ title: "New", color: "green" }}
/>;
```
