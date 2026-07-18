# Calendar

**Import:** `import { Calendar } from "@opal/components";`

Month grid on `react-day-picker`, the Figma `Date Picker`. Accepts the DayPicker selection modes (`single`, `multiple`, `range`), navigation props (`month`, `defaultMonth`, `startMonth`, `endMonth`, `numberOfMonths`), and `disabled` matchers. Opal owns all chrome: the styling and slot escape hatches (`className`/`classNames`, `style`/`styles`, `components`, `formatters`, `modifiersClassNames`, `modifiersStyles`, `showOutsideDays`) are stripped, and outside-month cells stay empty while keeping their 28px slot so week rows keep even spacing.

```tsx
<Calendar
  mode="single"
  selected={date}
  onSelect={setDate}
  disabled={[{ after: new Date() }]}
/>
```

## Anatomy

| Part | Spec |
|---|---|
| Month | 232px wide, caption row + weekday header + weeks |
| Caption | Month label in `main-ui-action` / `text-04`, prev/next `internal` icon buttons top-right |
| Weekday | 28px cell, `secondary-body` / `text-03` |
| Day chip | 28px (`--height-line-h3-section`), `rounded-08`, `main-ui-mono` numeral in `text-04` |
| Hover | `tint-02` fill with `border-02` outline |
| Selected / range endpoints | `tint-inverted-03` chip with `text-inverted-05` numeral |
| Range middle | `tint-02` band spanning the week, rounded at week edges |
| Today | Underlined numeral |
| Disabled | `text-01` numeral, not clickable |

Requires the `react-day-picker` peer dependency.
