# Input Layouts

**Import:** `import { InputVertical, InputHorizontal, ... } from "@opal/layouts";`

Layout primitives for form fields. Arrange title, description, input controls, and Formik error
messages in vertical or horizontal orientations with optional `<label>` wrapping. Uses
`sizePreset="main-ui"` internally for all text sizing.

## Components

### Label

Low-level `<label>` wrapper with cursor styling. Most consumers should use `InputVertical` or
`InputHorizontal` with `withLabel` instead of using `Label` directly.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `label` | `string` | — | Sets `htmlFor` to associate with a form element by id |
| `disabled` | `boolean` | `false` | Switches cursor to `not-allowed` |

### Vertical

Stacks title, description, input, error, and sub-description vertically.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `withLabel` | `boolean \| string` | `false` | `false`: no label. `true`: implicit label (click-forwarding). `string`: label with `htmlFor` + Formik error display. |
| `disabled` | `boolean` | `false` | Passes through to the label wrapper |
| `title` | `string \| RichStr` | — | Section title |
| `tag` | `TagProps` | — | Tag rendered beside the title |
| `description` | `string \| RichStr` | — | Section description |
| `subDescription` | `string \| RichStr` | — | Text below the input |
| `suffix` | `"optional" \| string` | — | Suffix after the title |

### Horizontal

Places title/description on the left, input control on the right.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `withLabel` | `boolean \| string` | `false` | Same as Vertical |
| `disabled` | `boolean` | `false` | Passes through to the label wrapper |
| `center` | `boolean` | `false` | Vertically center the input with the label |
| `title` | `string \| RichStr` | — | Section title |
| `tag` | `TagProps` | — | Tag rendered beside the title |
| `description` | `string \| RichStr` | — | Section description |
| `suffix` | `"optional" \| string` | — | Suffix after the title |

### InputErrorText

Renders an error or warning message with an icon.

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `children` | `ReactNode` | — | Error/warning message |
| `type` | `"error" \| "warning"` | `"error"` | Controls icon and color |

### InputDivider

A horizontal rule with inline padding for separating field groups.

### InputPadder

Wraps children in standard `p-2 w-full` padding.

## Usage

```tsx
import { InputVertical, InputHorizontal } from "@opal/layouts";

// Vertical with Formik field binding
<InputVertical withLabel="email" title="Email" description="Your email address">
  <InputTypeInField name="email" />
</InputVertical>

// Horizontal with implicit label (click-forwarding)
<InputHorizontal withLabel title="Notifications" description="Enable notifications">
  <Switch />
</InputHorizontal>

// No label (default) — for non-form children like buttons
<InputHorizontal title="Delete" description="Remove this item">
  <Button variant="danger">Delete</Button>
</InputHorizontal>
```
