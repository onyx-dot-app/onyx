# Tag

**Import:** `import { Tag, type TagProps } from "@opal/components";`

A small colored label used to annotate items with status, category, or metadata. Fixed at 1rem height, uses `font-figure-small-value`.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `title` | `string` | **(required)** | Tag label text |
| `color` | `TagColor` | `"gray"` | Color variant |
| `icon` | `IconFunctionComponent` | — | Optional icon before the title |

### `TagColor`

`"green" | "blue" | "purple" | "amber" | "gray"`

| Color | Background | Text |
|---|---|---|
| `green` | `theme-green-01` | `theme-green-05` |
| `blue` | `theme-blue-01` | `theme-blue-05` |
| `purple` | `theme-purple-01` | `theme-purple-05` |
| `amber` | `theme-amber-01` | `theme-amber-05` |
| `gray` | `background-tint-02` | `text-03` |

## Usage Examples

```tsx
import { Tag } from "@opal/components";
import SvgStar from "@opal/icons/star";

// Basic
<Tag title="New" color="green" />

// With icon
<Tag icon={SvgStar} title="Featured" color="purple" />

// Default gray
<Tag title="Draft" />
```

## Usage inside Content

Tag can be rendered as an accessory inside `Content`'s LabelLayout via the `tag` prop:

```tsx
import { Content } from "@opal/layouts";
import SvgSearch from "@opal/icons/search";

<Content
  icon={SvgSearch}
  sizePreset="main-ui"
  title="My Item"
  tag={{ title: "New", color: "green" }}
/>
```
