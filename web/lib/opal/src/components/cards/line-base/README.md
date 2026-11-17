# LineBase

**Internal.** Not exported from `@opal/components`, except its types
(`LineStatus`, `LineVariant`, `LineWeight`). Imported directly by
[`Line`](../line/README.md) and [`Log`](../../log/README.md).

The parts both lines share:

| Part          | What it draws                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------------- |
| `LineRoot`    | The frame: rounding, the status colour of the icon, the heavy tint over the row and the body, and the card flavour's padding and fill |
| `LineRow`     | The row, 1.75rem tall plus `padding`: the icon, the content and `rightChildren`                   |
| `LineSurface` | A `tertiary` `Interactive.Stateless` surface; a click anywhere in it but a link calls `onClick`   |
| `LineBody`    | The body, in a `Fold`, indented to start under the content; `inset`: `around` (default) pads the start, end and bottom, `start` only the start and 0.25rem on top, `top` only 0.25rem on top |

`Line` wraps only `LineRow` in `LineSurface`, so its body keeps its own clicks,
and gives its body `inset="start"`.
`Log` wraps `LineRow` and `LineBody` together, so the whole log is one surface.

## Variants

`LineVariant` is `"default"` or a status and a weight, e.g. `"error-heavy"`.
See [`Line`](../line/README.md#variants) for the colours.
