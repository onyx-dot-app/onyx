# InputMultiSelect

**Import:** `import { InputMultiSelect, type InputMultiSelectProps } from "@opal/components";`

Several picks from a set, with nothing to type. The chosen options are `Tag`
chips that make up the whole field on the `.opal-input` chrome; a focusable
combobox element takes the keyboard, a click toggles the list open and closed
(focus alone does not open it), and the list always shows the full set. The
type-in sibling is [InputMultiComboBox](../input-multi-combo-box/README.md).

A chosen option becomes a tag whose `id` is the option's `value` (via
`onSelectOption`); choosing it again, in the list or on the chip, removes it
through `onRemoveTag`. A chip shows its option's `icon`, when it has one. A
tag outside the set flags the chrome's error variant. `search` and
foldable dividers work as on [InputSingleSelect](../input-single-select/README.md#search).

```tsx
<InputMultiSelect
  tags={tags}
  options={groupOptions}
  onSelectOption={(option) =>
    setTags((prev) => [...prev, { id: option.value, label: option.title }])
  }
  onRemoveTag={(id) => setTags((prev) => prev.filter((t) => t.id !== id))}
  placeholder={t("groups.placeholder")}
/>
```

## Props

Every [InputTypeInTag](../../texts/input-type-in-tag/README.md) chrome prop (`tags`, `onRemoveTag`, `variant`, `disabled`, `icon`, `onClear`, `minRows`, `maxRows`), plus:

| Prop                | Type                                | Default        | Description                                                        |
| ------------------- | ----------------------------------- | -------------- | ------------------------------------------------------------------ |
| `options`           | `SelectOptions` | **(required)** | Loose options and dividers, in order        |
| `onSelectOption`    | `(option: SelectOption) => void`    | **(required)** | Called when an option is chosen                                    |
| `placeholder`       | `string`                            | **(required)** | Names the combobox element and shows while there are no chips      |
| `search`        | `boolean`                           | `false`        | A search field at the top of the list filters the rows; see [InputSingleSelect](../input-single-select/README.md#search) |
| `dropdownMaxHeight` | `string`                            | `"15rem"`      | Max height of the dropdown in CSS units                            |

Formik: `InputMultiSelectField` from `@opal/form`, whose value is `string[]` of option values.
