# InputSwitch

An accessible toggle switch with hover, focus, and disabled states.

Supports both **controlled** and **uncontrolled** modes.

## Usage

```tsx
import { InputSwitch } from "@opal/components";

// Uncontrolled
<InputSwitch defaultChecked onCheckedChange={(checked) => console.log(checked)} />

// Controlled
<InputSwitch checked={value} onCheckedChange={setValue} />

// Disabled
<InputSwitch disabled />
```

## Props

| Prop              | Type                         | Default     | Description                                                                       |
| ----------------- | ---------------------------- | ----------- | --------------------------------------------------------------------------------- |
| `checked`         | `boolean`                    | `undefined` | Controlled checked state.                                                         |
| `defaultChecked`  | `boolean`                    | `false`     | Initial state for uncontrolled mode.                                              |
| `onCheckedChange` | `(checked: boolean) => void` | `undefined` | Called with the new value when toggled.                                           |
| `disabled`        | `boolean`                    | `false`     | Blocks toggling, applies muted styles, and takes the switch out of the Tab order. |

All other `<button>` attributes (except `style`, `className`, `onChange`, and `type` — the switch is always `type="button"`) are forwarded.

## Layout

The `<button>` is the track, 32×18px. A wrapping `<div>` pads it by 1px vertically and 2px horizontally, as in the design mocks, and is fixed to the `height-line-main` token (20px) so a parent's line box or stretch cannot grow it. The rendered footprint is 36×20px.

## Visual States

| State        | Track color             | Thumb color                   |
| ------------ | ----------------------- | ----------------------------- |
| Off          | `background-tint-03`    | `background-neutral-light-00` |
| On           | `action-selection-05`   | `background-neutral-light-00` |
| Disabled off | `background-neutral-04` | `background-neutral-03`       |
| Disabled on  | `action-selection-03`   | `background-neutral-03`       |

Hover and keyboard focus (`:focus-visible`) both darken the track by one step. There is no focus border. A disabled switch that keeps focus (see below) gets the same darkening on its track; its thumb keeps the disabled colour.

## Focus

`disabled` sets `aria-disabled`, not the native `disabled` attribute. Callers often disable a switch while its change saves, and a browser drops focus from a natively disabled button. So a focused switch keeps focus through that save. While it is disabled, Enter and Space do nothing. When the save ends, they toggle it again without tabbing back. A disabled switch is still skipped by Tab (`tabIndex={-1}`).

## Formik

Use `InputSwitchField` from `@opal/form` for a Formik `boolean` field. It takes every `InputSwitch` prop except `checked`, and its `id` defaults to `name`.
