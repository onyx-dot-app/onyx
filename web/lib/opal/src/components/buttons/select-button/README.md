# SelectButton

**Import:** `import { SelectButton, type SelectButtonProps } from "@opal/components";`

A stateful button — the stateful counterpart to `Button`. Built on `Interactive.Stateful` > `Interactive.Container`. One component covers three jobs:

- **Toggle** — a togglable selection, optionally with a `rightIcon`.
- **Dropdown trigger** — `chevron` adds a trailing chevron that rotates while the trigger is open.
- **Filter** — `variant="select-filter"` + `chevron` + `onClear`: while `state="selected"`, a clear (X) button replaces the chevron.

## Open state

Inside a Radix trigger (`data-state="open"`) or an Opal `Dropdown.Trigger` (`aria-expanded`), the button reads the open state and shows its hover look — and, with `chevron`, rotates the chevron. An explicit `interaction` prop wins. Chevron rotation is CSS-driven (`buttons/chevron.css`).

## Architecture

```
Tooltip
  └─ div.relative?                   (only with onClear — positions the clear button)
       ├─ Interactive.Stateful       <- variant, state, interaction, disabled, onClick
       │    └─ Interactive.Container <- height, rounding, padding (from `size`)
       │         └─ div.opal-select-content
       │              ├─ Icon?
       │              ├─ [Foldable]?  (wraps label + trailing icon when foldable)
       │              │    ├─ label
       │              │    └─ rightIcon | chevron
       │              └─ label? / rightIcon | chevron  (non-foldable)
       └─ clear Button?              (onClear, while state="selected")
```

`foldable` uses `interactive-foldable-host` + `Interactive.Foldable`: the left icon stays visible while the label and trailing icon collapse until hover.

## Props

| Prop             | Type                                                       | Default          | Description                                                            |
| ---------------- | ---------------------------------------------------------- | ---------------- | ---------------------------------------------------------------------- |
| `variant`        | `"select-light" \| "select-heavy" \| "select-filter" \| …` | `"select-heavy"` | Stateful color variant                                                 |
| `state`          | `"empty" \| "filled" \| "selected"`                        | `"empty"`        | Current value state                                                    |
| `interaction`    | `"rest" \| "hover" \| "active"`                            | auto             | Overrides the open-state detection                                     |
| `icon`           | `IconFunctionComponent`                                    | —                | Left icon                                                              |
| `children`       | `string \| RichStr`                                        | —                | Label text                                                             |
| `rightIcon`      | `IconFunctionComponent`                                    | —                | Right icon. Not with `chevron`                                         |
| `chevron`        | `boolean`                                                  | `false`          | Trailing chevron for dropdown and popover triggers                     |
| `onClear`        | `() => void`                                               | —                | With `chevron`: a clear (X) button replaces the chevron while selected |
| `foldable`       | `boolean`                                                  | `false`          | Label + trailing icon collapse when not hovered                        |
| `size`           | `SizeVariant`                                              | `"lg"`           | Size preset                                                            |
| `width`          | `WidthVariant`                                             | —                | Width preset                                                           |
| `justifyContent` | `"between"`                                                | —                | Icon + label to the left, trailing icon to the right edge              |
| `labelFont`      | `TextFont`                                                 | size-derived     | Overrides the label font                                               |
| `labelColor`     | `TextColor`                                                | variant's color  | Overrides the label color                                              |
| `rounding`       | `Rounding`                                                 | size-derived     | Overrides the rounding                                                 |
| `tooltip`        | `string`                                                   | —                | Tooltip text                                                           |
| `tooltipSide`    | `TooltipSide`                                              | `"top"`          | Tooltip placement                                                      |
| `disabled`       | `boolean`                                                  | `false`          | Disables the button                                                    |

## Usage

```tsx
import { Dropdown, SelectButton } from "@opal/components";
import { SvgFilter, SvgStar } from "@opal/icons";

// Toggle
<SelectButton
  icon={SvgStar}
  state={isFavorite ? "selected" : "empty"}
  onClick={toggleFavorite}
>
  Favorite
</SelectButton>

// Dropdown trigger — the chevron rotates while open
<Dropdown>
  <Dropdown.Trigger asChild>
    <SelectButton chevron icon={SvgStar}>
      Sort
    </SelectButton>
  </Dropdown.Trigger>
  <Dropdown.Data items={items} />
</Dropdown>

// Filter — a clear button replaces the chevron while a filter is set
<SelectButton
  variant="select-filter"
  chevron
  icon={SvgFilter}
  state={hasFilter ? "selected" : "empty"}
  onClear={clearFilter}
>
  Status
</SelectButton>
```
