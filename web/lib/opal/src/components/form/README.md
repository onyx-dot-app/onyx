# Form

**Import:** `import { FormField, FormikField, FieldMessage, InputTypeInField } from "@opal/components";`

The form field layer: the presentational `FormField` chrome (label, description, control slot, validation message) plus a thin [Formik](https://formik.org) binding layer (`FormikField`, the `Field` wrappers, and the `useOn*` hooks).

`FormField` is state-driven and has no dependency on Formik. `FormikField` and the `*Field` wrappers are the glue that maps Formik state onto it, so `FormField` stays usable with any form library or with plain React state.

## Pieces

| Export | Role |
|---|---|
| `FormField` | Compound presentational field: `Root` + `Label` + `Description` + `Control` + `Message` + `APIMessage` |
| `FieldMessage` | Standalone inline message row (icon + text) used by `FormField.Message` |
| `FormikField` | Render-prop that reads a Formik field and derives its `idle \| success \| error` state |
| `useFieldContext` | Reads the `FormField` context (`baseId`, `state`, `describedByIds`, …) from a descendant |
| `InputTypeInField` | `InputTypeIn` bound to a Formik field (mirrors error state, forwards `onChange`/`onBlur`) |
| `CheckboxField` | `Checkbox` bound to a Formik boolean field |
| `LabeledCheckboxField` | `Checkbox` with a label, optional sublabel, and optional tooltip |
| `SwitchField` | `Switch` bound to a Formik boolean field |
| `useOnChangeEvent` / `useOnChangeValue` / `useOnBlurEvent` | Formik event adapters for building custom `Field` wrappers |

## FormField

`FormField` derives ARIA wiring (`aria-invalid`, `aria-describedby`, `aria-required`, matched `id`s) from a single `state`. Drive `state` yourself, or let `FormikField` supply it.

```tsx
import { FormField, InputTypeIn } from "@opal/components";

<FormField state="error" required>
  <FormField.Label required>Email</FormField.Label>
  <FormField.Description>We only use this for account notifications.</FormField.Description>
  <FormField.Control>
    <InputTypeIn placeholder="you@example.com" value={value} onChange={onChange} />
  </FormField.Control>
  <FormField.Message messages={{ error: "Enter a valid email.", idle: "" }} />
</FormField>
```

- **`FormField.Control`** injects the ARIA attributes onto its single child via `cloneElement` (or Radix `Slot` when `asChild`).
- **`FormField.Message`** picks the message for the current `state` from `messages`. `success` with no message falls back to the `idle` message.
- **`FormField.APIMessage`** is the async variant, keyed on `idle | success | error | loading` for server-driven feedback.

## Formik binding

`FormikField` reads a field by `name` and passes `(field, helper, meta, state)` to its render prop, where `state` is `meta.touched ? (meta.error ? "error" : "success") : "idle"`.

```tsx
import { Formik, Form } from "formik";
import { FormField, FormikField, InputTypeInField } from "@opal/components";

<Formik initialValues={{ email: "" }} validate={validate} onSubmit={onSubmit}>
  <Form>
    <FormikField
      name="email"
      render={(_field, _helper, meta, state) => (
        <FormField state={state} required>
          <FormField.Label required>Email</FormField.Label>
          <FormField.Control>
            <InputTypeInField name="email" placeholder="you@example.com" />
          </FormField.Control>
          <FormField.Message messages={{ error: meta.error ?? "", idle: "" }} />
        </FormField>
      )}
    />
  </Form>
</Formik>
```

### Building your own Field wrapper

The `useOn*` hooks adapt a control's callbacks to Formik without re-reading the whole field:

- `useOnChangeEvent(name, onChange?)`: for native event controls (calls `field.onChange`).
- `useOnChangeValue(name, onChange?)`: for value controls (calls `setValue` + `setTouched(true)`).
- `useOnBlurEvent(name, onBlur?)`: marks the field touched on blur.

```tsx
function MyField({ name, ...props }: { name: string }) {
  const [field] = useField<string>(name);
  const onChange = useOnChangeValue<string>(name);
  return <MyControl value={field.value} onChange={onChange} {...props} />;
}
```
