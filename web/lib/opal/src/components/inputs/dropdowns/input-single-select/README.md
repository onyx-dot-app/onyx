# InputSingleSelect

**Import:** `import { InputSingleSelect, type InputSingleSelectProps, type SelectOption, type SelectDivider, type SelectOptions } from "@opal/components";`

A single pick from a set, with nothing to type. The trigger is an input-shaped
button: like a native `<select>`, a click or ArrowDown opens the full set, a
second click closes it, and keyboard focus alone does not open it. Keyboard
navigation (arrows, Enter, Escape) and ARIA combobox semantics are built in.
The type-in sibling is [InputSingleComboBox](../input-single-combo-box/README.md).

Re-picking the selected option unselects it (the value becomes `""` and the
placeholder shows).

## Default option

With `defaultOption` the select never reads as empty: an empty `value` resolves
to it, and re-picking the selected option does nothing, like a native
`<select>`. `onValueChange` never receives `""`.
`placeholder` stays required: it is the field's accessible name even when the
default keeps the trigger filled.

`options` is a list of loose options and dividers in any order, like
`<option>`s beside `<optgroup>`s: a divider is `{ title?, options }` and renders
a separator line above its rows, carrying `title` when there is one. The trigger shows the chosen option's `icon`, when it has one. A value
outside the set shows the placeholder with the validation error.

```tsx
<InputSingleSelect
  value={strategy}
  onValueChange={setStrategy}
  defaultOption="reindex"
  placeholder="Select a strategy"
  options={[
    { options: [{ value: "none", title: "Do not re-index" }] },
    {
      title: "Re-index options",
      options: [
        { value: "reindex", title: "Re-index all, then switch" },
        { value: "instant", title: "Switch, then re-index" },
      ],
    },
  ]}
/>
```

## Props

| Prop            | Type                                | Default | Description                                                     |
| --------------- | ----------------------------------- | ------- | --------------------------------------------------------------- |
| `value`         | `string`                            | —       | Current value (controlled)                                      |
| `onValueChange` | `(value: string) => void`           | —       | Fires on a pick, and with `""` on an unpick                     |
| `options`       | `SelectOptions` | `[]`    | Loose options and dividers, in order                        |
| `defaultOption` | `string`                            | —       | Option value an empty `value` resolves to; never empties then   |
| `placeholder`   | `string`                            | —       | Shown while empty; always the accessible name (required)        |
| `isError`       | `boolean`                           | —       | External error state (overrides internal validation)            |
| `rightChildren` | `React.ReactNode`                   | —       | Extra trigger-side controls                                     |

Formik: `InputSingleSelectField` from `@opal/form`.
