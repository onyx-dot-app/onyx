# InputCurrency

**Import:** `import { InputCurrency } from "@opal/components";`

Segmented currency amount field on the shared `.opal-input` chrome. Mono segments read `$ [whole] . [fraction]`. The host locale sets the symbol, the side it sits on (`3,00 €`) and the decimal separator.

- Typing `.`, `,` or the locale separator in the whole segment jumps to the fraction.
- Pasting `12.50` into the whole segment fills both segments.
- `precision` governs the fraction: typing past it is blocked.
- The whole segment always resolves: leading zeros trim as soon as focus leaves it (`0007` becomes `7`, `0000` becomes `0`).
- Left/Right arrows cross segment edges, and Backspace in an empty fraction returns to the whole segment.
- Edits report through `onChange` as you type, so a form sees the amount at once. An empty field reports `null`.
- Enter steps from the whole segment to the fraction, like Tab. In the last segment it tidies the display (`3.5` becomes `3.50`) and submits a surrounding form.
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
