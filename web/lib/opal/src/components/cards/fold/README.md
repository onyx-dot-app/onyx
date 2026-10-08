# CardFold

**Internal.** Not exported from `@opal/components`. Imported directly by
[`Card`](../card/README.md) and [`SelectCard`](../select-card/README.md).

The animating body of an expandable card, built on [`Fold`](../../fold/README.md).
A grid row moves between `0fr` and `1fr` with an opacity fade over 200ms, so the fold opens and closes on a pure
CSS clock: no measured height, no state machine, no Radix, and the children
are dropped once it closes.

## Structure

```
.opal-fold              grid 0fr ↔ 1fr, opacity fade (the shared `Fold`)
  .opal-fold-inner     min-height: 0, clips the grid child
    .opal-card-fold-body border minus its top edge, bottom rounding
```

## Props

| Prop            | Type              | Default | Description                                                         |
| --------------- | ----------------- | ------- | ------------------------------------------------------------------- |
| `expanded`      | `boolean`         | —       | Whether the fold is open. Visual only; the host card owns the state |
| `border`        | `BorderVariants`  | —       | Border style, matched to the header above                           |
| `radius`        | `string`          | —       | Bottom corner radius in rem, matched to the header's                |
| `borderColor`   | `StatusVariants`  | —       | Status border colour, for hosts that have one                       |
| `contentHeight` | `80 \| "full"`    | `80`    | `80` caps the body at 20rem with scroll; `"full"` does not cap      |
| `children`      | `React.ReactNode` | —       | The folded content                                                  |

## Notes

- **A closed fold holds nothing.** Children linger through the closing
  animation, so it has something to collapse, then unmount. Anything else
  leaves a hidden copy of the content on the page: still fetching, still
  matching a query by test id or field name, and still counted by anything
  that walks the DOM rather than the accessibility tree.
- **Closing means inert.** During that window the fold sets `inert` and
  `aria-hidden`, so its children leave the tab order and the accessibility
  tree the moment it starts to close.
- **No background.** The body is transparent, so the page shows through and
  the fold stays visually distinct from the header above it.
- **No top border.** The header's bottom border is the seam between the two.
- **No padding.** The host card's `padding` applies to its header only;
  callers pad whatever they put inside the fold.
- **The host owns the seam.** Each card flattens its own header corners and
  keeps that border at its resting colour while the fold is open.
