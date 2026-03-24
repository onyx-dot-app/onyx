# FilterButton

**Import:** `import { FilterButton, type FilterButtonProps } from "@opal/components";`

A stateful filter trigger with a built-in chevron (when empty) and a clear button (when selected). Hardcodes `variant="select-filter"` and delegates to `Interactive.Stateful`, adding automatic open-state detection from Radix `data-state`. Designed to sit inside a `Popover.Trigger` for filter dropdowns.

## Relationship to OpenButton

FilterButton shares a similar call stack to `OpenButton`:

```
Interactive.Stateful → Interactive.Container → content row (icon + label + trailing indicator)
```

FilterButton is a **narrower, filter-specific** variant:

- It hardcodes `variant="select-filter"` (OpenButton uses `"select-heavy"`)
- Its `state` is limited to `"empty" | "selected"` (OpenButton supports `"filled"` too)
- When selected, the chevron is replaced by an absolutely-positioned clear `Button` with `prominence="tertiary"` — placed as a sibling outside the `<button>` to avoid nesting buttons
- It uses the shared `ChevronIcon` from `buttons/chevron` (same as OpenButton)
- It does not support `foldable`, `size`, or `width` — it is always `"lg"`

## Architecture

```
div.relative                               <- bounding wrapper
  Interactive.Stateful                     <- variant="select-filter", interaction, state
    └─ Interactive.Container (button)      <- height="lg", default rounding/padding
         └─ div.interactive-foreground
              ├─ div > Icon                (interactive-foreground-icon)
              ├─ <span>                    label text
              └─ ChevronIcon               (when empty)
                 OR spacer div             (when selected — reserves chevron space)
  div.absolute                             <- clear Button overlay (when selected)
    └─ Button (SvgX, size="2xs", prominence="tertiary")
```

- **Open-state detection** reads `data-state="open"` injected by Radix triggers (e.g. `Popover.Trigger`), falling back to the explicit `interaction` prop.
- **Chevron rotation** uses the shared `ChevronIcon` component and `buttons/chevron.css`, which rotates 180deg when `data-interaction="hover"`.
- **Clear button** is absolutely positioned outside the `<button>` element tree to avoid invalid nested `<button>` elements. An invisible spacer inside the button reserves the same space so layout doesn't shift between states.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `icon` | `IconFunctionComponent` | **required** | Left icon component |
| `children` | `string` | **required** | Label text between icon and trailing indicator |
| `state` | `"empty" \| "selected"` | `"empty"` | Whether the filter has an active selection |
| `onClear` | `() => void` | — | Called when the clear (X) button is clicked |
| `interaction` | `"rest" \| "hover" \| "active"` | auto | JS-controlled interaction override. Falls back to Radix `data-state="open"`. |
| `tooltip` | `string` | — | Tooltip text shown on hover |
| `tooltipSide` | `TooltipSide` | `"top"` | Which side the tooltip appears on |

## Usage

```tsx
import { FilterButton } from "@opal/components";
import { SvgUser } from "@opal/icons";

// Inside a Popover (auto-detects open state)
<Popover.Trigger asChild>
  <FilterButton
    icon={SvgUser}
    state={hasSelection ? "selected" : "empty"}
    onClear={() => clearSelection()}
  >
    {hasSelection ? selectionLabel : "Everyone"}
  </FilterButton>
</Popover.Trigger>
```
