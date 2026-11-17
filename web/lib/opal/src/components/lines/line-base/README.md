# LineBase

**Internal.** Not exported from `@opal/components`, except its types
(`LineStatus`, `LineVariant`, `LineWeight`). Imported directly by
[`Line`](../line/README.md) and [`LogLine`](../log-line/README.md).

The parts both lines share:

| Part          | What it draws                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------------- |
| `LineRoot`    | The frame: rounding, the status colour of the icon, the heavy tint over the row and the body, and the card flavour's padding and fill |
| `LineRow`     | The row, 1.75rem tall plus `padding`: the icon, the content and `rightChildren`                   |
| `LineSurface` | A `tertiary` `Interactive.Stateless` surface over the row and the body; only a click on the row (not a link, not ending a selection) calls `onClick` |
| `LineBody`    | The body, in a `Fold`. `inset`: `around` (default) under the icon's column with the line's padding on the end and bottom, `top` only 0.25rem on top (a card) |

`Line` (its step flavour) and `LogLine` wrap `LineRow` and `LineBody` in
`LineSurface`: one hover surface, toggled only from the row.

## Variants

`LineVariant` is `"default"` or a status and a weight, e.g. `"error-heavy"`.
See [`Line`](../line/README.md#variants) for the colours.
