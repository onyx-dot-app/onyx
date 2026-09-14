# InputMultiSelect

**Import:** `import { InputMultiSelect, type InputMultiSelectProps, type TagItem } from "@opal/components";`

Chips-in-input, the Figma `Input/Tags` component: editable `Tag`s rendered inline with a text input on the `.opal-input` chrome.

Interaction model:

- Enter adds the trimmed input text via `onAdd`.
- Backspace on an empty input arms the last tag (its dark keyboard-selection state).
- Backspace or Delete on an armed tag removes it and focus returns to the input. Enter and Space also activate the armed remove button.
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
| `focusOnMount` | `boolean`                            | `false`        | Focuses the text input on mount                                                   |

### `TagItem`

`TagItem` is `{ id: string; label: string; error?: boolean }`. `error` shows the warning indicator on that tag.

## Usage

```tsx
import { InputMultiSelect, type TagItem } from "@opal/components";

const [tags, setTags] = useState<TagItem[]>([]);
const [draft, setDraft] = useState("");

<InputMultiSelect
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

Deferred from the Figma spec: the `resizable` corner handle and the extra `action` button slot.

## The option set (family dropdown)

Passing `options` (flat `SelectOption[]` or sectioned `SelectSection[]`)
enables the family's unified dropdown under the field: typing filters, arrows
navigate, Enter picks. A chosen option becomes a tag whose `id` is the
option's `value` (via `onSelectOption`); choosing it again — in the dropdown
or on the chip — removes it through `onRemoveTag`. Sections render with a
`Divider` between them.

- **`mode="closed"`** (default): only options can be chosen.
- **`mode="open"`**: the raw text can also be committed via the create row
  (`createPrefix` labels it), landing in `onAdd` like a plain tag.

Without `options` the input is the plain free-tagging field — an open set
by definition, so the types accept only `mode="open"` there (`"closed"`
without a set is a contradiction and does not compile).

```tsx
<InputMultiSelect
  tags={tags}
  value={query}
  onChange={setQuery}
  options={groups.map((g) => ({
    value: String(g.id),
    label: g.name,
    description: t("memberCount", { count: g.users.length }),
  }))}
  onSelectOption={(option) =>
    setTags((prev) => [...prev, { id: option.value, label: option.label }])
  }
  onRemoveTag={(id) => setTags((prev) => prev.filter((t) => t.id !== id))}
  onAdd={() => {}}
  placeholder={t("search.placeholder")}
/>
```
