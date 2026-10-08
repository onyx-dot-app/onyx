# OverflowText

**Import:** `import { OverflowText } from "@opal/components";`

`Text` clamped to a number of lines. While the clamp cuts the text, hovering it
shows the full text in a tooltip. Text that fits gets no tooltip, so short
labels stay plain.

## Props

Every `Text` prop except `children`, `maxLines` and `ref`, plus:

| Prop          | Type                | Default | Description                               |
| ------------- | ------------------- | ------- | ----------------------------------------- |
| `children`    | `string \| RichStr` | —       | The text; it also fills the tooltip       |
| `maxLines`    | `number`            | `1`     | Lines shown before the text is cut        |
| `tooltipSide` | `TooltipSide`       | `"top"` | Which side the full-text tooltip opens on |

## Notes

- Overflow is measured with `useOverflow`, so it updates when the text's box
  resizes or a webfont loads.
- A one-line clamp needs a block box: render it as a flex item or with a
  block `as` tag, as `Text`'s `maxLines` does.
- The tooltip opens on hover only.

## Usage

```tsx
<OverflowText font="main-ui-body" color="text-04">
  {message}
</OverflowText>
```
