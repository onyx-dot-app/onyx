# InputDatePicker

**Import:** `import { InputDatePicker } from "@opal/components";`

Segmented date field on the shared `.opal-input` chrome, the Figma `Input/Date`. Mono `MM/DD/YYYY` segments accept typed input (auto-advance, backspace to the previous segment, commit on blur or Enter once the segments form a real in-range date), and the calendar action opens the Opal `Calendar` in a popover for click selection. Invalid or out-of-range typing reverts to the committed value.

```tsx
<InputDatePicker
  value={date}
  onChange={setDate}
  maxDate={new Date()}
  clearable
/>
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `value` | `Date \| null` | — | Selected date (required, controlled) |
| `onChange` | `(date: Date \| null) => void` | — | Fires on commit, `null` when cleared |
| `error` | `boolean` | `false` | Error chrome on the field |
| `disabled` | `boolean` | `false` | Disabled chrome, segments and calendar action inert, clear action hidden |
| `clearable` | `boolean` | `false` | Shows a clear action while a value is set and the field is enabled |
| `minDate` | `Date` | — | Earliest selectable day (inclusive) |
| `maxDate` | `Date` | — | Latest selectable day (inclusive) |
| `id` | `string` | — | Applied to the month segment for `<label htmlFor>` |

Date ranges (the Figma `Range` variant) are not implemented yet. The `Calendar` beneath already supports `mode="range"`, so a range picker is an API addition here, not a new surface.
