# InputSingleSelect

**Import:** `import { InputSingleSelect, type InputSingleSelectProps, type SelectOption, type SelectSection } from "@opal/components";`

The single-arity member of the `input-select` family: an input-shaped trigger
over the family's unified dropdown. Typing always filters the option set;
keyboard navigation (arrows, Enter, Escape) and ARIA combobox semantics are
built in. With no options it degrades to a plain input.

The set-openness axis:

- **`mode="closed"`** (default) — only option values are allowed. The trigger
  shows the selected option's label at rest; a value outside the set shows a
  validation error.
- **`mode="open"`** — typing filters AND the raw text can be committed as a
  value via the create row (prefix it with `createPrefix`, e.g. "Use").

Options are flat or sectioned. Sections render in order with a `Divider`
between each and an optional muted heading; a section whose options all
filter out disappears.

```tsx
<InputSingleSelect
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
<InputSingleSelect
  mode="open"
  value={model}
  onValueChange={setModel}
  options={modelOptions}
  placeholder="Select or enter model"
  createPrefix="Use"
/>
```

## Props

Key props (`InputSingleSelectProps` also passes DOM input attributes through):

| Prop            | Type                                   | Default    | Description                                          |
| --------------- | -------------------------------------- | ---------- | ---------------------------------------------------- |
| `value`         | `string`                               | —          | Current value (controlled)                           |
| `onValueChange` | `(value: string) => void`              | —          | Fires on option selection (and create-row commit)    |
| `onChange`      | `(e) => void`                          | —          | Fires on every keystroke (controlled-input style)    |
| `options`       | `SelectOption[] \| SelectSection[]`    | `[]`       | The set; sectioned options render with Dividers      |
| `mode`          | `"closed" \| "open"`                   | `"closed"` | Set openness                                         |
| `placeholder`   | `string`                               | —          | Trigger placeholder (required)                       |
| `createPrefix`  | `string`                               | —          | Prefix on the open-mode create row (e.g. "Use")      |
| `isError`       | `boolean`                              | —          | External error state (overrides internal validation) |
| `rightChildren` | `React.ReactNode`                      | —          | Extra trigger-side controls                          |

The dropdown itself (`dropdown/`) is a family-internal component — never
consumed directly by app code.
