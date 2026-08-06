# ProgressBar

A determinate progress bar. Renders a track with a fill whose width is
`value / max` (clamped to `[0, 1]`).

```tsx
import { ProgressBar } from "@opal/components";

<ProgressBar value={completed} max={total} color="blue" />;
```

## Props

| Prop    | Type                                     | Default  | Notes                        |
| ------- | ---------------------------------------- | -------- | ---------------------------- |
| `value` | `number`                                 | —        | Current progress.            |
| `max`   | `number`                                 | `100`    | Denominator. `0` renders 0%. |
| `color` | `"blue" \| "green" \| "red" \| "purple"` | `"blue"` | Fill color (token-backed).   |

Structural sizing (height 6px, radius 4px) is fixed in `styles.css`; colors are
token classes so light/dark mode is handled by `colors.css`. Exposes
`role="progressbar"` with `aria-valuenow/min/max`.
