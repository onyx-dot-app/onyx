# Checkbox

**Import:** `import { Checkbox, type CheckboxProps } from "@opal/components";`

A dual-element checkbox with custom styling. Uses a hidden native `<input>` for form state and a visible `<div>` for the visual surface. Supports controlled, uncontrolled, indeterminate, and disabled modes.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `checked` | `boolean` | — | Controlled checked state |
| `defaultChecked` | `boolean` | `false` | Initial state for uncontrolled mode |
| `onCheckedChange` | `(checked: boolean) => void` | — | Called when the checked state changes |
| `indeterminate` | `boolean` | `false` | Shows a dash instead of a check |
| `disabled` | `boolean` | `false` | Prevents interaction |
| `className` | `string` | — | Additional classes for the visual surface |
| `id` | `string` | — | Passed to the hidden `<input>` for label association |
| `name` | `string` | — | Form field name |

All remaining props are forwarded to the hidden `<input>` element.

## Styles

Visual states are driven by `data-*` attributes on the surface element and
defined in `styles.css`:

| Attribute | Values | Description |
|---|---|---|
| `data-state` | `"unchecked"` \| `"checked"` \| `"indeterminate"` | Current checkbox state |
| `data-disabled` | present / absent | Disables interaction and applies muted colors |

### Color matrix

| State | Background | Border |
|---|---|---|
| Unchecked | `background-neutral-00` | `border-02` (hover: `border-03`) |
| Checked / Indeterminate | `action-link-05` (hover: `action-link-04`) | — |
| Disabled unchecked | `background-neutral-03` | `border-02` |
| Disabled checked | `background-neutral-04` | — |

### CSS classes

| Class | Element | Description |
|---|---|---|
| `.opal-checkbox` | Root wrapper | `inline-flex shrink-0` |
| `.opal-checkbox-surface` | Visual surface | 16x16, rounded, state-driven colors |
| `.opal-checkbox-input` | Hidden `<input>` | Screen-reader only |
| `.opal-checkbox-icon` | Check / dash icon | 12x12, `stroke-text-light-05` |

## Usage Examples

```tsx
import { Checkbox } from "@opal/components";

// Uncontrolled
<Checkbox onCheckedChange={(checked) => console.log(checked)} />

// Controlled
<Checkbox checked={isChecked} onCheckedChange={setIsChecked} />

// With label
<div className="flex items-center gap-2">
  <Checkbox id="terms" />
  <label htmlFor="terms">Accept terms</label>
</div>

// Indeterminate (e.g. "select all" with partial selection)
<Checkbox indeterminate />

// Disabled
<Checkbox disabled checked />
```
