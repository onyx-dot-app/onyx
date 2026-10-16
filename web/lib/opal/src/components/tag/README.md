# Tag

**Import:** `import { Tag, type TagProps } from "@opal/components";`

A small colored label used to annotate items with status, category, or metadata. Two types, matching the Figma `Tag` component:

- **Passive** (default): metadata label. 1rem tall with `font-figure-small-value` at `sm`, 1.375rem with `secondary-body` at `md`.
- **Editable** (`onRemove` set): remove button, gray hover, and a dark focus-within treatment chip fields use as the keyboard-selection state before deleting a tag.
- **Clickable** (`onClick` set): renders a `button` with the tag metrics. As a `Popover.Trigger` or `Dropdown.Trigger` child it inverts (`background-tint-inverted-03`, `text-inverted-05`) while `data-state="open"` or `aria-expanded="true"`. An icon with its own `iconColor` keeps that color.

The passive look comes in three variants:

| Variant   | Background        | Icon                  | Label     | Use                                     |
| --------- | ----------------- | --------------------- | --------- | --------------------------------------- |
| `default` | the color's `-01` | the color's text      | the color's text | Category and metadata labels    |
| `status`  | the color's `-01` | the color's text      | `text-04` | Status pills (Indexing, Paused, Failed) |
| `count`   | none              | the color's text      | `text-04` | Warning and failure counts in rows      |

Status tags use `font="secondary-body"`; `sm` keeps `figure-small-value` by default.

## Props

| Prop       | Type                    | Default        | Description                                                                                    |
| ---------- | ----------------------- | -------------- | ---------------------------------------------------------------------------------------------- |
| `title`    | `string \| RichStr`     | **(required)** | Tag label text                                                                                 |
| `color`    | `TagColor`              | `"gray"`       | Color variant                                                                                  |
| `variant`  | `"default" \| "status" \| "count"` | `"default"` | Passive look: colored label, `text-04` label on a tint, or `text-04` label with no background |
| `iconColor` | `TagColor`             | `color`        | Icon color when it differs from `color` (a gray pill with an orange warning icon)              |
| `onClick`  | `MouseEventHandler<HTMLButtonElement>` | —   | Renders the tag as a button; inverts while an attached popover or dropdown is open. Not allowed with `onRemove`. `ref` is then a `Ref<HTMLButtonElement>`; otherwise a `Ref<HTMLDivElement>` |
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

### `TagColor`

`"green" | "blue" | "purple" | "amber" | "orange" | "red" | "gray"`

| Color    | Background           | Text                                       |
| -------- | -------------------- | ------------------------------------------ |
| `green`  | `theme-green-01`     | `theme-green-05`                           |
| `blue`   | `theme-blue-01`      | `theme-blue-05`                            |
| `purple` | `theme-purple-01`    | `theme-purple-05`                          |
| `amber`  | `theme-amber-01`     | `theme-amber-05`                           |
| `orange` | `status-warning-01`  | `status-warning-05`                        |
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

// Status pill: tinted background, colored icon, text-04 label
<Tag icon={SvgPause} title="Paused" color="amber" variant="status" font="secondary-body" />

// Gray pill with an orange icon
<Tag icon={SvgAlertTriangle} title="3 warnings" iconColor="orange" variant="status" />

// Count: no background, colored icon, text-04 number
<Tag icon={SvgAlertTriangle} title="12" color="orange" variant="count" />

// Clickable trigger: inverts while the popover is open
<Popover>
  <Popover.Trigger asChild>
    <Tag icon={SvgAlertCircle} title="Stack Trace" color="red" variant="status" onClick={() => {}} />
  </Popover.Trigger>
  <Popover.Content>…</Popover.Content>
</Popover>

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
