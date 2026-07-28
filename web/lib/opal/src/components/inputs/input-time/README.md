# InputTime

**Import:** `import { InputTime, type TimeValue } from "@opal/components";`

Segmented 24-hour time field on the shared `.opal-input` chrome, the Figma `Input/Time`. Mono `HH:MM:SS` segments accept typed input (auto-advance, backspace to the previous segment, commit on blur or Enter once the segments form a valid time), and invalid drafts revert to the committed value. No picker surface, the field is the whole interaction.

```tsx
<InputTime value={time} onChange={setTime} clearable />
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `value` | `TimeValue \| null` | — | Selected time, 24-hour (required, controlled) |
| `onChange` | `(time: TimeValue \| null) => void` | — | Fires on commit, `null` when cleared |
| `error` | `boolean` | `false` | Error chrome on the field |
| `disabled` | `boolean` | `false` | Disabled chrome, segments inert, clear action hidden |
| `clearable` | `boolean` | `false` | Shows a clear action while a value is set and the field is enabled |
| `showSeconds` | `boolean` | `true` | Shows the seconds segment. Hidden seconds commit as zero. |
| `id` | `string` | — | Applied to the hours segment for `<label htmlFor>` |

`TimeValue` is `{ hours: number; minutes: number; seconds: number }`, always 24-hour. The segment chrome is shared with `InputDatePicker` (`.opal-input-segment` in `inputs/shared.css`).
