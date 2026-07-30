# InputTags

**Import:** `import { InputTags, type InputTagsProps, type TagItem } from "@opal/components";`

Chips-in-input, the Figma `Input/Tags` component: editable `Tag`s rendered inline with a text input on the `.opal-input` chrome.

Interaction model:

- Enter adds the trimmed input text via `onAdd`.
- Backspace on an empty input arms the last tag (its dark keyboard-selection state).
- Backspace or Delete on an armed tag removes it and focus returns to the input. Enter and Space also activate the armed remove button.
- Clicking the field focuses the input.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `tags` | `TagItem[]` | **(required)** | Tags rendered before the input |
| `onRemoveTag` | `(id: string) => void` | **(required)** | Remove handler |
| `onAdd` | `(value: string) => void` | **(required)** | Called with trimmed text on Enter (no-op when empty) |
| `value` | `string` | **(required)** | Controlled input text |
| `onChange` | `(value: string) => void` | **(required)** | Input change handler |
| `placeholder` | `string` | — | Input placeholder |
| `variant` | `"primary" \| "internal" \| "error"` | `"primary"` | Wrapper chrome. `"internal"` is the borderless Figma `Style=Subtle` look |
| `disabled` | `boolean` | `false` | Dims the field, disables input, hides remove and clear buttons |
| `icon` | `IconFunctionComponent` | — | Leading icon (24px container) |
| `onClear` | `() => void` | — | Renders the clear action button |

### `TagItem`

`TagItem` is `{ id: string; label: string; error?: boolean }`. `error` shows the warning indicator on that tag.

## Usage

```tsx
import { InputTags, type TagItem } from "@opal/components";

const [tags, setTags] = useState<TagItem[]>([]);
const [draft, setDraft] = useState("");

<InputTags
  tags={tags}
  onRemoveTag={(id) => setTags(tags.filter((t) => t.id !== id))}
  onAdd={(label) => {
    setTags([...tags, { id: crypto.randomUUID(), label }]);
    setDraft("");
  }}
  value={draft}
  onChange={setDraft}
  placeholder="Add a tag…"
/>
```

Deferred from the Figma spec: the `resizable` corner handle and the extra `action` button slot.
