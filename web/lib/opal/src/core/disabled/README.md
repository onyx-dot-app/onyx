# Disabled

**Import:** `import { Disabled } from "@opal/core";`

Wrapper component that applies baseline disabled CSS (opacity, cursor, pointer-events) to its
children. Renders a `<div>` with the `data-opal-disabled` attribute so styling cascades into all
descendants. Works with any children — DOM elements, React components, or fragments.

When `disabled` is true, it also blocks the keyboard: the children sit in a `<fieldset>` (with
`display: contents`) that is disabled, so the form controls inside leave the tab order and take no
input. `allowClick` keeps the children interactive, so it leaves the keyboard enabled too. The
fieldset is always rendered, so toggling `disabled` does not remount the children.

A `tooltip` only shows on hover, and nothing in a disabled region can take focus to open it. So
`Disabled` also keeps the tooltip's plain text in a visually hidden, polite live region while it is
disabled: screen readers read the reason in the region and announce it when it changes.

## Props

| Prop          | Type                                     | Default   | Description                                                                         |
| ------------- | ---------------------------------------- | --------- | ----------------------------------------------------------------------------------- |
| `disabled`    | `boolean`                                | `false`   | Applies disabled styling when truthy                                                |
| `allowClick`  | `boolean`                                | `false`   | Re-enables pointer events and keyboard input while keeping disabled visuals         |
| `tooltip`     | `string \| RichStr`                      | —         | Tooltip shown on hover when disabled (implies `allowClick`). Supports `markdown()`. |
| `tooltipSide` | `"top" \| "bottom" \| "left" \| "right"` | `"right"` | Which side the tooltip appears on                                                   |

## CSS behavior

| Selector                                 | Effect                                                                         |
| ---------------------------------------- | ------------------------------------------------------------------------------ |
| `[data-opal-disabled]`                   | `cursor-not-allowed`, `select-none`, `pointer-events: none`                    |
| `[data-opal-disabled]:not(.interactive)` | `opacity-50` (non-Interactive elements only)                                   |
| `[data-opal-disabled].interactive`       | `pointer-events: auto` (Interactive elements handle their own disabled colors) |
| `[data-opal-disabled][data-allow-click]` | `pointer-events: auto`                                                         |

## Usage

```tsx
// Basic — disables children visually and blocks pointer events
<Disabled disabled={!canSubmit}>
  <Card>Content</Card>
</Disabled>

// With tooltip — explains why the section is disabled
<Disabled disabled={!canSubmit} tooltip="Complete the form first">
  <Card>Content</Card>
</Disabled>

// With allowClick — keeps pointer events for custom handling
<Disabled disabled={isProcessing} allowClick>
  <MyInputBar />
</Disabled>
```
