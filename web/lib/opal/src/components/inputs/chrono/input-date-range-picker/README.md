# InputDateRangePicker

**Import:** `import { InputDateRangePicker, rangeForInclusiveDays, type DateRange } from "@opal/components";`

A preset-strip date-range control: 1D / 7D / 1M / 3M buttons plus a "Custom" trigger that opens
the Opal `Calendar` in a popover for an arbitrary range. The active custom range renders as its
formatted span (e.g. "Mar 3 – Apr 1"). Built on `SelectButton`, `Popover`, and `Calendar`.

## Props

| Prop            | Type                         | Default | Description                                 |
| --------------- | ---------------------------- | ------- | ------------------------------------------- |
| `value`         | `DateRange`                  | —       | Controlled range (or unset)                 |
| `onValueChange` | `(value: DateRange) => void` | —       | Fires on preset pick or custom-range commit |
| `size`          | `"md" \| "sm"`               | `"md"`  | Button size                                 |

All labels — preset names, the group and custom-range aria labels — come from `OpalStrings`
(`dateRange*` keys), bridged from the `opal.dateRange` catalog namespace.
