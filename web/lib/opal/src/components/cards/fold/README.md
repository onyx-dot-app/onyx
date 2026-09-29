# CardFold

**Internal.** Not exported from `@opal/components`. Imported directly by
[`Card`](../card/README.md) and [`SelectCard`](../select-card/README.md).

The animating body of an expandable card. A grid row moves between `0fr` and
`1fr` with an opacity fade over 200ms, so the fold opens and closes on a pure
CSS clock: no measured height, no state machine, no Radix, and the children
are never unmounted.

## Structure

```
.opal-card-fold          grid 0fr ↔ 1fr, opacity fade, overflow clip
  .opal-card-fold-inner  min-height: 0, clips the grid child
    .opal-card-fold-body border minus its top edge, bottom rounding
```

## Props

| Prop            | Type                | Default | Description                                                        |
| --------------- | ------------------- | ------- | ------------------------------------------------------------------ |
| `expanded`      | `boolean`           | —       | Whether the fold is open. Visual only; the host card owns the state |
| `border`        | `BorderVariants`    | —       | Border style, matched to the header above                          |
| `radius`        | `string`            | —       | Bottom corner radius in rem, matched to the header's               |
| `borderColor`   | `StatusVariants`    | —       | Status border colour, for hosts that have one                      |
| `contentHeight` | `80 \| "full"`      | `80`    | `80` caps the body at 20rem with scroll; `"full"` does not cap     |
| `children`      | `React.ReactNode`   | —       | The folded content                                                 |

## Notes

- **Closed means inert.** A closed fold keeps its children mounted at zero
  height, so it sets `inert` and `aria-hidden` to keep them out of the tab
  order and the accessibility tree.
- **No background.** The body is transparent, so the page shows through and
  the fold stays visually distinct from the header above it.
- **No top border.** The header's bottom border is the seam between the two.
- **No padding.** The host card's `padding` applies to its header only;
  callers pad whatever they put inside the fold.
- **The host owns the seam.** Each card flattens its own header corners and
  keeps that border at its resting colour while the fold is open.
