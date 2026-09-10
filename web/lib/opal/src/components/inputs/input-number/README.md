# InputNumber

**Import:** `import { InputNumber, type InputNumberProps } from "@opal/components";`

A number field with chevron stepper buttons and an optional reset-to-default action.
Free typing is validated on blur; stepping clamps to `min`/`max`.

## Props

| Prop            | Type                              | Default     | Description                       |
| --------------- | --------------------------------- | ----------- | --------------------------------- |
| `value`         | `number \| null`                  | —           | Controlled value                  |
| `onChange`      | `(value: number \| null) => void` | —           | Fires on commit                   |
| `min` / `max`   | `number`                          | —           | Clamp bounds                      |
| `step`          | `number`                          | `1`         | Stepper increment                 |
| `decimalPlaces` | `number`                          | `0`         | Allowed precision                 |
| `defaultValue`  | `number`                          | —           | Target of the reset action        |
| `showReset`     | `boolean`                         | `false`     | Shows the reset button            |
| `variant`       | input variant union               | `"primary"` | Chrome variant (`data-color` CSS) |
| `disabled`      | `boolean`                         | `false`     | Disables input and steppers       |
