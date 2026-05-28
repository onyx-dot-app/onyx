# InputTypeIn

**Import:** `import { InputTypeIn } from "@opal/components";`

A styled text input with optional search icon, prefix text, clear button, and right section slot.
Visual states are driven by a `variant` prop; all border, background, and focus styles live in `styles.css`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `InputVariants` | `"primary"` | Visual state |
| `prefixText` | `string` | — | Non-editable prefix rendered before the input (e.g. `"https://"`) |
| `searchIcon` | `boolean` | `false` | Show a search icon on the left |
| `rightChildren` | `ReactNode` | — | Custom content rendered to the right of the input; suppresses the built-in clear button |
| `clearButton` | `boolean` | `false` | Show the clear (×) button when the field has a value; suppressed when `rightChildren` is set |
| `value` | `string` | — | Controlled value |
| `onChange` | `ChangeEventHandler` | — | Change handler |

`InputTypeIn` also forwards all standard `<input>` attributes (except `disabled` and `readOnly` — use `variant="disabled"` / `variant="readOnly"` instead).

## Variants

| Value | Description |
|-------|-------------|
| `"primary"` | Standard bordered input with hover/focus ring |
| `"internal"` | Borderless, transparent — for inputs embedded inside containers |
| `"error"` | Red border, indicates a validation error |
| `"disabled"` | Muted background, not-allowed cursor, non-interactive |
| `"readOnly"` | Transparent background, light border, non-editable |

## Usage

```tsx
// Basic
<InputTypeIn value={value} onChange={(e) => setValue(e.target.value)} />

// Search
<InputTypeIn searchIcon placeholder="Search..." value={q} onChange={(e) => setQ(e.target.value)} />

// Error state
<InputTypeIn variant="error" value={value} onChange={...} />

// With prefix
<InputTypeIn prefixText="https://" value={url} onChange={...} />

// Custom right section (password reveal) — suppresses clear button automatically
<InputTypeIn
  value={password}
  onChange={...}
  rightChildren={<Button icon={SvgEye} onClick={toggle} prominence="internal" />}
/>
```
