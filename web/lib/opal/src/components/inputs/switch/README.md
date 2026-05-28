# Switch

An accessible toggle switch with hover, focus, and disabled states.

Supports both **controlled** and **uncontrolled** modes.

## Usage

```tsx
import { Switch } from "@opal/components";

// Uncontrolled
<Switch defaultChecked onCheckedChange={(checked) => console.log(checked)} />

// Controlled
<Switch checked={value} onCheckedChange={setValue} />

// Disabled
<Switch disabled />
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `checked` | `boolean` | `undefined` | Controlled checked state. |
| `defaultChecked` | `boolean` | `false` | Initial state for uncontrolled mode. |
| `onCheckedChange` | `(checked: boolean) => void` | `undefined` | Called with the new value when toggled. |
| `disabled` | `boolean` | `false` | Disables interaction and applies muted styles. |

All other `<button>` attributes (except `style`, `className`, and `onChange`) are forwarded.

## Visual States

| State | Track color | Thumb color |
|-------|-------------|-------------|
| Off | `background-tint-03` | `background-neutral-light-00` |
| On | `action-link-05` | `background-neutral-light-00` |
| Disabled off | `background-neutral-04` | `background-neutral-03` |
| Disabled on | `action-link-03` | `background-neutral-03` |

Hover darkens the track by one step; focus adds a border ring.
