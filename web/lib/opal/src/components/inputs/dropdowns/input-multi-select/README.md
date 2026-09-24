# InputMultiSelect

**Import:** `import { InputMultiSelect, type InputMultiSelectProps } from "@opal/components";`

The multi-arity member of the input-select family: [InputTypeInTag](../../texts/input-type-in-tag/README.md)'s chips-in-input chrome over the family's unified dropdown. Typing filters the option set, arrows navigate, Enter picks, and a chosen option becomes a `Tag`.

Free tagging with no set to pick from is `InputTypeInTag` itself. `InputMultiSelect` always has an option set, so `options` is required.

## Props

Every [InputTypeInTag](../../texts/input-type-in-tag/README.md) prop, plus:

| Prop                | Type                                  | Default    | Description                                                                              |
| ------------------- | ------------------------------------- | ---------- | ---------------------------------------------------------------------------------------- |
| `options`           | `SelectOption[] \| SelectSection[]`   | **(required)** | The selectable set, flat or sectioned. Sections render with a `Divider` between them |
| `onSelectOption`    | `(option: SelectOption) => void`      | **(required)** | Called when a dropdown option is chosen                                              |
| `mode`              | `"closed" \| "open"`                  | `"closed"` | Set openness, see below                                                                  |
| `dropdownMaxHeight` | `string`                              | `"15rem"`  | Max height of the dropdown in CSS units                                                  |

`onAdd` is the create row's commit in `mode="open"`. In `mode="closed"` it never fires.

## The option set

A chosen option becomes a tag whose `id` is the option's `value` (via `onSelectOption`); choosing it again — in the dropdown or on the chip — removes it through `onRemoveTag`.

- **`mode="closed"`** (default): only options can be chosen. A committed tag outside the set (a stale seed, or the options shrank) flags the chrome's error variant.
- **`mode="open"`**: the raw text can also be committed via the create row, landing in `onAdd` like a plain tag. Free-form tags then appear at the top of the dropdown as selected rows, like the single's, and picking one again removes it through `onRemoveTag`.

Closing the dropdown drops whatever was typed: the filter is transient UI state, so the component clears `value` through `onChange`.

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
