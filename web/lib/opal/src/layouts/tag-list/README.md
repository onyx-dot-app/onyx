# TagList

**Import:** `import { TagList, type TagListProps } from "@opal/layouts";`

Wrap-flowing row of `Tag`s outside an input, for any labelled list. Use it instead of hand-mapping `Tag`s at call sites.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `items` | `TagItem[]` | **(required)** | `{ id, label, error? }`, the same item type `InputTags` uses |
| `onRemove` | `(id: string) => void` | — | Renders a remove button on every item tag. Omit for passive tags |
| `maxVisible` | `number` | — | Collapse items beyond this count into a "+N" tag whose tooltip names the hidden entries |
| `overflowIcon` | `IconFunctionComponent` | — | Icon on the "+N" overflow tag |

## Usage

```tsx
<TagList
  items={tags}
  onRemove={(id) => setTags(tags.filter((t) => t.id !== id))}
  maxVisible={5}
/>
```

Tags render truncated (`truncate`) so long labels ellipsize with the default title tooltip. There is no Figma component for a standalone tag row. Sizing and spacing follow the `Input/Tags` tag row.
