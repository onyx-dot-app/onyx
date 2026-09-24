# InputSingleSelect

**Import:** `import { InputSingleSelect, type InputSingleSelectProps, type SelectOption, type SelectSection } from "@opal/components";`

A single pick from a set, with nothing to type. The trigger is an input-shaped
button: like a native `<select>`, a click or ArrowDown opens the full set, a
second click closes it, and keyboard focus alone does not open it. Keyboard
navigation (arrows, Enter, Escape) and ARIA combobox semantics are built in.
The type-in sibling is [InputSingleComboBox](../input-single-combo-box/README.md).

Re-picking the selected option unselects it (the value becomes `""` and the
placeholder shows).

## Default option

With `defaultOption` the select never reads as empty: an empty `value` resolves
to it, re-picking the default itself does nothing, and re-picking any other
selected option falls back to the default. `onValueChange` never receives `""`.
The trigger then always has a label, so `placeholder` becomes optional.

Options are flat or sectioned. Sections render in order with a `Divider`
between each and an optional titled heading. A value outside the set shows the
placeholder with the validation error.

```tsx
<InputSingleSelect
  value={strategy}
  onValueChange={setStrategy}
  defaultOption="reindex"
  options={[
    { options: [{ value: "none", label: "Do not re-index" }] },
    {
      label: "Re-index options",
      options: [
        { value: "reindex", label: "Re-index all, then switch" },
        { value: "instant", label: "Switch, then re-index" },
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
| `options`       | `SelectOption[] \| SelectSection[]` | `[]`    | The set; sectioned options render with Dividers                 |
| `defaultOption` | `string`                            | —       | Option value an empty `value` resolves to; never empties then   |
| `placeholder`   | `string`                            | —       | Trigger placeholder (required without `defaultOption`)          |
| `isError`       | `boolean`                           | —       | External error state (overrides internal validation)            |
| `rightChildren` | `React.ReactNode`                   | —       | Extra trigger-side controls                                     |

Formik: `InputSingleSelectField` from `@opal/form`.
