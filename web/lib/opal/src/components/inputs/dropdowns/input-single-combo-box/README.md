# InputSingleComboBox

**Import:** `import { InputSingleComboBox, type InputSingleComboBoxProps, type SelectOption, type SelectSection } from "@opal/components";`

A single pick from a set behind a text input: typing filters the options, focus
opens the list, and a click while focused reopens it. Keyboard navigation
(arrows, Enter, Escape) and ARIA combobox semantics are built in. `options` is
required; for a plain text input use `InputTypeIn`. The pick-only sibling is
[InputSingleSelect](../input-single-select/README.md).

The set-openness axis:

- **`mode="closed"`** (default) — only option values are allowed. The trigger
  shows the selected option's label at rest; a value outside the set shows a
  validation error.
- **`mode="open"`** — typing filters AND the raw text can be committed as a
  value via the create row.

Re-picking the selected option unselects it. There is no `defaultOption`: the
text is the filter, so a default would pre-fill it with a label the user never
chose and the opened list would show only that row.

Options are flat or sectioned. Sections render in order with a `Divider`
between each and an optional titled heading; a section whose options all
filter out disappears.

```tsx
<InputSingleComboBox
  value={model}
  onValueChange={setModel}
  placeholder="Choose a model"
  options={[
    {
      label: "OpenAI",
      options: [{ value: "gpt", label: "GPT-5", description: "Default" }],
    },
    { label: "Anthropic", options: [{ value: "opus", label: "Claude Opus" }] },
  ]}
/>

// Open set: pick a suggestion or type a custom model name.
<InputSingleComboBox
  mode="open"
  value={model}
  onValueChange={setModel}
  options={modelOptions}
  placeholder="Select or enter model"
/>
```

## Props

Key props (`InputSingleComboBoxProps` also passes DOM input attributes through):

| Prop            | Type                                | Default    | Description                                          |
| --------------- | ----------------------------------- | ---------- | ---------------------------------------------------- |
| `value`         | `string`                            | —          | Current value (controlled)                           |
| `onValueChange` | `(value: string) => void`           | —          | Fires on option selection (and create-row commit)    |
| `onChange`      | `(e) => void`                       | —          | Fires on every keystroke (controlled-input style)    |
| `options`       | `SelectOption[] \| SelectSection[]` | `[]`       | The set; sectioned options render with Dividers      |
| `mode`          | `"closed" \| "open"`                | `"closed"` | Set openness                                         |
| `placeholder`   | `string`                            | —          | Trigger placeholder (required)                       |
| `isError`       | `boolean`                           | —          | External error state (overrides internal validation) |
| `rightChildren` | `React.ReactNode`                   | —          | Extra trigger-side controls                          |

Formik: `InputSingleComboBoxField` from `@opal/form`. The dropdown itself
(`dropdown/`) is a family-internal component, never consumed directly by app code.
