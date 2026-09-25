# InputTypeInTag

**Import:** `import { InputTypeInTag, type InputTypeInTagProps, type TagItem } from "@opal/components";`

Free tagging, the Figma `Input/Tags` component: editable `Tag`s rendered inline with a text input on the `.opal-input` chrome. There is nothing to select from. A field that offers a set of options is [InputMultiSelect](../../selects/input-multi-select/README.md), which renders the same chrome over the select family's dropdown.

Interaction model:

- Enter adds the trimmed input text via `onAdd`.
- Backspace on an empty input, or ArrowLeft with the caret at the start, arms the last tag (its dark keyboard-selection state). ArrowLeft and ArrowRight walk the armed tags; ArrowRight off the last returns to the input. Tags are not Tab stops, so Tab leaves the field.
- Backspace or Delete on an armed tag removes it and arms the tag before it, so repeated presses clear tags one by one; with none left, focus returns to the input. Enter and Space also activate the armed remove button.
- Clicking the field focuses the input.

## Props

| Prop           | Type                                 | Default        | Description                                                                       |
| -------------- | ------------------------------------ | -------------- | --------------------------------------------------------------------------------- |
| `tags`         | `TagItem[]`                          | **(required)** | Tags rendered before the input                                                    |
| `onRemoveTag`  | `(id: string) => void`               | **(required)** | Remove handler                                                                    |
| `onAdd`        | `(value: string) => void`            | **(required)** | Called with trimmed text on Enter (no-op when empty)                              |
| `value`        | `string`                             | **(required)** | Controlled input text                                                             |
| `onChange`     | `(value: string) => void`            | **(required)** | Input change handler                                                              |
| `placeholder`  | `string`                             | —              | Input placeholder                                                                 |
| `variant`      | `"primary" \| "internal" \| "error"` | `"primary"`    | Wrapper chrome. `"internal"` is the borderless Figma `Style=Subtle` look          |
| `disabled`     | `boolean`                            | `false`        | Dims the field, disables input, hides remove and clear buttons                    |
| `icon`         | `IconFunctionComponent`              | —              | Leading icon (24px container)                                                     |
| `onClear`      | `() => void`                         | —              | Renders the clear action button                                                   |
| `minRows`      | `number`                             | `1`            | Tag rows the field is tall enough to show before it grows. Rows pack from the top |
| `maxRows`      | `number`                             | `2`            | Tag rows the field grows to before the chips scroll inside it. A new chip scrolls the input row into view |
| `focusOnMount` | `boolean`                            | `false`        | Focuses the text input on mount                                                   |

### `TagItem`

`TagItem` is `{ id: string; label: string; icon?: IconFunctionComponent; error?: boolean }`. `icon` leads the tag; `error` shows the warning indicator on it.

## Usage

```tsx
import { InputTypeInTag, type TagItem } from "@opal/components";

const [tags, setTags] = useState<TagItem[]>([]);
const [draft, setDraft] = useState("");

<InputTypeInTag
  tags={tags}
  onRemoveTag={(id) => setTags(tags.filter((t) => t.id !== id))}
  onAdd={(label) => {
    setTags([...tags, { id: crypto.randomUUID(), label }]);
    setDraft("");
  }}
  value={draft}
  onChange={setDraft}
  placeholder="Add a tag…"
/>;
```

The caller owns the text: `onAdd` does not clear `value`, so clear it there.

## `TagField`

`TagField.tsx` holds the chips-in-input chrome itself, plus the hooks a select needs to mount a dropdown on it (`rootRef`, `inputRef`, `onInputKeyDown`, `inputAriaProps`, trailing `children`). It is internal to Opal and not exported from `@opal/components`.

Deferred from the Figma spec: the `resizable` corner handle and the extra `action` button slot.
