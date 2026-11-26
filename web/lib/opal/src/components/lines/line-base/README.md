# LineBase

**Internal.** Not exported from `@opal/components`, except its types
(`LineStatus`, `LineVariant`, `LineWeight`). Imported directly by
[`Line`](../line/README.md) and [`LogLine`](../log-line/README.md).

The parts the lines are built from:

| Part          | What it draws                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------------- |
| `LineRoot`    | The frame: rounding, the status colour of the icon, the heavy tint over the row and the body, and a card's (`Line`'s) padding and fill |
| `LineRow`     | The row, 1.75rem tall plus `padding`: the icon, the content and `rightChildren`                   |
| `LineSurface` | A `tertiary` `Interactive.Stateless` surface over the row and the body; only a click on the row (not a link, not ending a selection) calls `onClick` |

`LogLine` wraps `LineRow` and its body in `LineSurface`: one hover surface,
toggled only from the row. `Line` uses only `LineRoot`. Both lines open and
fold their body with `Collapsible.Root` and `Collapsible.Content`; the body is a
`.opal-line-body`, which these styles indent.

## Variants

`LineVariant` is `"default"` or a status and a weight, e.g. `"error-heavy"`.
See [`LogLine`](../log-line/README.md#variants) for the colours.
