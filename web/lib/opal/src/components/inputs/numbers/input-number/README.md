# InputNumber

**Import:** `import { InputNumber, type InputNumberProps } from "@opal/components";`

A number field with chevron stepper buttons and an optional reset-to-default action.
Typing is free: any number can be typed, and leaving the field clamps it to `min`/`max`. For a Formik field, use `InputNumberField` from `@opal/form`, which also flags an out-of-range value while it is typed. Stepping clamps to both bounds. The chrome is the shared `.opal-input`, and the unit shows in `text-02`.
With a negative `min`, the value can be typed with a leading minus sign.

## Props

| Prop            | Type                              | Default     | Description                                                                           |
| --------------- | --------------------------------- | ----------- | ------------------------------------------------------------------------------------- |
| `value`         | `number \| null`                  | —           | Controlled value                                                                      |
| `onChange`      | `(value: number \| null) => void` | —           | Fires on each valid keystroke, on blur, and on a stepper or reset click               |
| `onCommit`      | `(value: number \| null) => void` | —           | Fires with the settled value on blur and on a stepper or reset click. Use it to save. |
| `min` / `max`   | `number`                          | —           | Bounds: the steppers and blur clamp to them                                           |
| `step`          | `number`                          | `1`         | Stepper increment                                                                     |
| `decimalPlaces` | `number`                          | `0`         | Allowed precision                                                                     |
| `defaultValue`  | `number`                          | —           | Target of the reset action                                                            |
| `showReset`     | `boolean`                         | `false`     | Shows the reset button                                                                |
| `variant`       | input variant union               | `"primary"` | Chrome variant (`data-variant` CSS)                                                   |
| `disabled`      | `boolean`                         | `false`     | Disables input and steppers                                                           |
| `placeholder`   | `string`                          | —           | Shown while the field is empty                                                        |
| `suffix`        | `string`                          | —           | Unit text after the value                                                             |
| `id`            | `string`                          | —           | Input id, for `<label htmlFor>`                                                       |
| `allowEmpty`    | `boolean`                         | `true`      | When false, blur restores a blank field instead of committing `null`                  |
| `plain`         | `boolean`                         | `false`     | A plain type-in field: no steppers, the value in mono, the unit in `text-02`          |
