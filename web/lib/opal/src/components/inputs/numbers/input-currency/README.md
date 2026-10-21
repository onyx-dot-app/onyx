# InputCurrency

**Import:** `import { InputCurrency } from "@opal/components";`

Segmented currency amount field on the shared `.opal-input` chrome. Mono segments read `$ [whole] . [fraction]`. The host locale sets the symbol, the side it sits on (`3,00 €`) and the decimal separator.

- Typing the locale decimal separator in the whole segment jumps to the fraction, filling an empty whole segment with `0` (`.5` reads `0 . 5`). Arrows, Tab and Enter only move focus and fill nothing. The grouping separator (`,` in `1,200`) and other non-digits do nothing.
- Pasting reads the text as an amount, whichever segment has focus. Whitespace, grouping and the currency's symbol or code are dropped; the rest must be digits with at most one decimal separator:
  - one separator replaces both segments (`1.2` → `1 . 2`, `$1,234.56` → `1234 . 56`);
  - none inserts the digits into the focused segment at the caret;
  - anything else (`1.2.3`, `a1b2c3`, `-5`) is ignored.
- `precision` governs the fraction: typing past it is blocked.
- The whole segment always resolves: leading zeros trim as soon as focus leaves it (`0007` becomes `7`, `0000` becomes `0`).
- Arabic-Indic digits read as ASCII digits, and the number stays left to right on right-to-left pages. With no fraction segment (`precision={0}`, JPY), input stops at the decimal separator: pasting `12.50` gives `12`.
- Left/Right arrows cross segment edges, and Backspace in an empty fraction returns to the whole segment.
- Edits report through `onChange` as you type, so a form sees the amount at once. An empty field reports `null`.
- Inside a form, Enter tidies the display (`3.5` becomes `3.50`) and submits the form from either segment, like any text input. Outside a form, Enter steps from the whole segment to the fraction, like Tab.
- Blur also tidies the display.

```tsx
<InputCurrency value={rate} onChange={setRate} precision={6} />
```

## Props

| Prop            | Type                                     | Default                   | Description                                                                 |
| --------------- | ---------------------------------------- | ------------------------- | --------------------------------------------------------------------------- |
| `value`         | `number \| null`                         | —                         | The amount (required, controlled). Negative values render empty.            |
| `onChange`      | `(value: number \| null) => void`        | —                         | Fires on each edit, `null` when cleared                                      |
| `currency`      | `string`                                 | `"USD"`                   | ISO 4217 code. Sets the symbol, its side and the default decimals.          |
| `precision`     | `number`                                 | the currency's (USD `2`)  | Most fraction digits; typing more is blocked. `0` hides the fraction segment. |
| `placeholder`   | `{ whole?: string; fraction?: string }`  | `"0"` / `"00"`            | Segment placeholders                                                        |
| `error`         | `boolean`                                | `false`                   | Error chrome on the field                                                   |
| `disabled`      | `boolean`                                | `false`                   | Disabled chrome, segments inert                                             |
| `id`            | `string`                                 | —                         | Applied to the whole segment for `<label htmlFor>`                          |

## Locale

Opal has no locale of its own. The host supplies `OpalStrings.inputCurrencyParts`, which the app's `OpalStringsBridge` builds with `getCurrencyParts(locale, currency)`. Without a provider, the field uses `en-US`.

The display keeps the currency's usual decimals and trims extra trailing zeros: with `precision={6}`, `3` shows `3.00` and `0.075` shows `0.075`.
