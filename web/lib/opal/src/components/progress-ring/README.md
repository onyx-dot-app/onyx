# ProgressRing

A determinate progress ring: a faded track with an arc that runs clockwise from
the top. The arc covers `value / max` of the ring, clamped to `[0, 1]`. A value
of 0 draws only the track.

```tsx
import { ProgressRing } from "@opal/components";

<ProgressRing value={used} max={budget} />;
<ProgressRing value={tokens} max={limit} color="warning" size={16} />;
```

## Props

| Prop         | Type                                          | Default            | Notes                                         |
| ------------ | --------------------------------------------- | ------------------ | --------------------------------------------- |
| `value`      | `number`                                      | —                  | Current progress.                             |
| `max`        | `number`                                      | `100`              | Denominator. `0` renders 0%.                  |
| `color`      | `"blue" \| "neutral" \| "warning" \| "error"` | `"blue"`           | Arc colour.                                   |
| `track`      | `"tint" \| "border"`                          | `"tint"`           | `tint`: the arc colour at 20%. `border`: the neutral border grey (`border-03`). |
| `size`       | `number`                                      | `18`               | Width and height in px; the stroke scales.    |
| `aria-label` | `string`                                      | `"Progress"`       | Accessible name.                              |
| `aria-valuetext` | `string`                                  | —                  | Spoken value, e.g. a real value past the max. |
| `aria-hidden`| `boolean`                                     | `false`            | Hide the ring when visible text gives the value. |

The geometry follows the Figma progress icon: a 15px ring with a 1.5px stroke in
an 18px box. Exposes `role="progressbar"` with the drawn fraction as a percent
in `aria-valuenow` (0–100).
