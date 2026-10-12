# InputMultiComboBox

**Import:** `import { InputMultiComboBox, type InputMultiComboBoxProps } from "@opal/components";`

Several picks from a set behind a text input: [InputTypeInTag](../../texts/input-type-in-tag/README.md)'s chips-in-input chrome over the family's dropdown. Typing filters the option set and opens the list, as does a click, Enter or ArrowDown (focus alone does not); the arrows and Tab walk the rows and wrap around, Enter picks, and a chosen option becomes a `Tag`. The pick-only sibling is [InputMultiSelect](../input-multi-select/README.md).

Free tagging with no set to pick from is `InputTypeInTag` itself. `InputMultiComboBox` always has an option set, so `options` is required.

## The option set

A chosen option becomes a tag whose `id` is the option's `value` (via `onSelectOption`); choosing it again, in the list or on the chip, removes it through `onRemoveTag`. A chip shows its option's `icon`, when it has one.

- **`mode="closed"`** (default): only options can be chosen. A committed tag outside the set (a stale seed, or the options shrank) flags the chrome's error variant.
- **`mode="open"`**: the raw text can also be committed via the create row, landing in `onAdd` like a plain tag. Free-form tags then appear at the top of the list as selected rows, and picking one again removes it through `onRemoveTag`.

Closing the list drops whatever was typed: the filter is transient UI state, so the component clears `value` through `onChange`.

```tsx
<InputMultiComboBox
  tags={tags}
  value={query}
  onChange={setQuery}
  options={groups.map((g) => ({
    value: String(g.id),
    title: g.name,
    description: t("memberCount", { count: g.users.length }),
  }))}
  onSelectOption={(option) =>
    setTags((prev) => [...prev, { id: option.value, label: option.title }])
  }
  onRemoveTag={(id) => setTags((prev) => prev.filter((t) => t.id !== id))}
  onAdd={() => {}}
  placeholder={t("search.placeholder")}
/>
```

## Props

Every [InputTypeInTag](../../texts/input-type-in-tag/README.md) prop, plus:

| Prop                | Type                                | Default        | Description                                                        |
| ------------------- | ----------------------------------- | -------------- | ------------------------------------------------------------------ |
| `options`           | `SelectOptions` | **(required)** | Loose options and dividers, in order        |
| `onSelectOption`    | `(option: SelectOption) => void`    | **(required)** | Called when an option is chosen                                    |
| `mode`              | `"closed" \| "open"`                | `"closed"`     | Set openness, see above                                            |
| `dropdownMaxHeight` | `string`                            | `"15rem"`      | Max height of the dropdown in CSS units                            |

`onAdd` is the create row's commit in `mode="open"`. In `mode="closed"` it never fires.

Formik: `InputMultiComboBoxField` from `@opal/form`, whose value is `string[]` of option values.
