# InputTypeIn

**Import:** `import { InputTypeIn } from "@opal/components";`

A styled text input with optional search icon, prefix text, clear button, and right section slot.
Visual states are driven by a `variant` prop; all border, background, and focus styles live in `styles.css`.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `InputTypeInVariant` | `"primary"` | Visual state |
| `prefixText` | `string` | — | Non-editable prefix rendered before the input (e.g. `"https://"`) |
| `leftSearchIcon` | `boolean` | `false` | Show a search icon on the left |
| `rightSection` | `ReactNode` | — | Custom content rendered to the right of the input (replaces the built-in clear button area) |
| `showClearButton` | `boolean` | `true` | Show the clear (×) button when the field has a value |
| `onClear` | `() => void` | — | Called when the clear button is clicked; omit to use built-in synthetic event |
| `value` | `string` | — | Controlled value |
| `onChange` | `ChangeEventHandler` | — | Change handler |
| `readOnly` | `boolean` | `false` | Adds HTML `readOnly` without the `readOnly` variant styling |

`InputTypeIn` also forwards all standard `<input>` attributes (except `disabled` — use `variant="disabled"` instead).

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
<InputTypeIn leftSearchIcon placeholder="Search..." value={q} onChange={setQ} />

// Error state
<InputTypeIn variant="error" value={value} onChange={...} />

// With prefix
<InputTypeIn prefixText="https://" value={url} onChange={...} />

// Custom right section (password reveal)
<InputTypeIn
  value={password}
  onChange={...}
  showClearButton={false}
  rightSection={<Button icon={SvgEye} onClick={toggle} prominence="internal" />}
/>
```
