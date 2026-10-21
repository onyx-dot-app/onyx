# InputDatePicker

**Import:** `import { InputDatePicker } from "@opal/components";`

Segmented date field on the shared `.opal-input` chrome, the Figma `Input/Date`. Mono `MM/DD/YYYY` segments accept typed input (auto-advance, backspace to the previous segment, Left/Right arrows across segment edges, commit on blur or Enter once the segments form a real in-range date), and the calendar action opens the Opal `Calendar` in a popover for click selection. Invalid or out-of-range typing reverts to the committed value.

- Typing fills a segment with digits, and a full segment moves focus to the next one. Typing past a full segment is blocked.
- Typing a separator (`/`, `-` or `.`) in the month or day splits the segment at the caret: digits before it stay (`1` becomes `01`), digits after it move to the front of the next segment, and focus moves there. So `1/2/2026` types as `01 / 02 / 2026`. Other non-digits do nothing.
- Pasting reads the text as a date, whichever segment has focus. Whitespace and direction marks are dropped; the rest must be digits:
  - a whole date fills every segment: `10/19/2026`, `10-19-2026`, `10.19.2026`, or ISO `2026-10-19`;
  - digits alone go into the focused segment at the caret, clipped to fit;
  - anything else (`10/19`, `Oct 19 2026`, a two-digit year such as `1/2/26`) is ignored.
- A pasted date commits like a typed one: on blur or Enter.
- Arabic-Indic digits read as ASCII digits.

```tsx
<InputDatePicker
  value={date}
  onChange={setDate}
  maxDate={new Date()}
  clearable
/>
```

## Props

| Prop        | Type                           | Default | Description                                                              |
| ----------- | ------------------------------ | ------- | ------------------------------------------------------------------------ |
| `value`     | `Date \| null`                 | —       | Selected date (required, controlled)                                     |
| `onChange`  | `(date: Date \| null) => void` | —       | Fires on commit, `null` when cleared                                     |
| `error`     | `boolean`                      | `false` | Error chrome on the field                                                |
| `disabled`  | `boolean`                      | `false` | Disabled chrome, segments and calendar action inert, clear action hidden |
| `clearable` | `boolean`                      | `false` | Shows a clear action while a value is set and the field is enabled       |
| `minDate`   | `Date`                         | —       | Earliest selectable day (inclusive)                                      |
| `maxDate`   | `Date`                         | —       | Latest selectable day (inclusive)                                        |
| `id`        | `string`                       | —       | Applied to the month segment for `<label htmlFor>`                       |
| `placeholder` | `string`                     | —       | Shown instead of the empty segments until the field takes focus          |

Date ranges (the Figma `Range` variant) are not implemented yet. The `Calendar` beneath already supports `mode="range"`, so a range picker is an API addition here, not a new surface.
