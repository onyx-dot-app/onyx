# InputSingleComboBox

**Import:** `import { InputSingleComboBox, type InputSingleComboBoxProps, type SelectOption, type SelectDivider, type SelectOptions } from "@opal/components";`

A single pick from a set behind a text input: typing filters the options and
opens the list, as does a click, Enter or ArrowDown; focus alone does not, so
tabbing through a form passes by. Open, the arrows and Tab walk the rows and
wrap around, Enter picks, Escape closes, and ARIA combobox semantics are
built in. `options` is
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

`options` is a list of loose options and dividers in any order, like
`<option>`s beside `<optgroup>`s: a divider is `{ title?, options }` and renders
a separator line above its rows, carrying `title` when there is one.
A divider whose options all filter out disappears with its line. The trigger
is typed text, so it shows no option icon.

```tsx
<InputSingleComboBox
  value={model}
  onValueChange={setModel}
  placeholder="Choose a model"
  options={[
    {
      title: "OpenAI",
      options: [{ value: "gpt", title: "GPT-5", description: "Default" }],
    },
    { title: "Anthropic", options: [{ value: "opus", title: "Claude Opus" }] },
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
| `options`       | `SelectOptions` | `[]`       | Loose options and dividers, in order             |
| `mode`          | `"closed" \| "open"`                | `"closed"` | Set openness                                         |
| `placeholder`   | `string`                            | —          | Trigger placeholder (required)                       |
| `isError`       | `boolean`                           | —          | External error state (overrides internal validation) |
| `rightChildren` | `React.ReactNode`                   | —          | Extra trigger-side controls                          |

Formik: `InputSingleComboBoxField` from `@opal/form`. The dropdown itself
(`dropdown/`) is a family-internal component, never consumed directly by app code.
