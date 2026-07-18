# InputTextArea

**Import:** `import { InputTextArea, type InputTextAreaProps } from "@opal/components";`

Multiline text field on the shared `.opal-input` chrome. Accepts standard textarea attributes except `disabled` and `readOnly` (use the matching `variant`), `className`, and `style`.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `variant` | `InputVariants` | `"primary"` | Wrapper chrome variant |
| `rows` | `number` | `4` | Initial rows and the `autoResize` minimum. The field has a 48px min-height floor, so values below 2 rows render at the floor |
| `autoResize` | `boolean` | `false` | Grow with content between `rows` and `maxRows`, disables manual resizing |
| `maxRows` | `number` | — | Row cap for `autoResize`, content beyond it scrolls |
| `resizable` | `boolean` | `true` | Manual vertical resize handle, ignored with `autoResize` |
| `rightSection` | `ReactNode` | — | Slot pinned to the top-right inside the field |

## Usage

```tsx
<InputTextArea
  value={value}
  onChange={(event) => setValue(event.target.value)}
  placeholder="Enter a description…"
  autoResize
  rows={2}
  maxRows={8}
/>
```

The Figma Input family has no dedicated textarea component.
