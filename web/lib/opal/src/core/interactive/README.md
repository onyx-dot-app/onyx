# Interactive

The foundational layer for all clickable surfaces in the design system. Defines hover, active, disabled, and transient state styling in a single place. Higher-level components (Button, OpenButton, etc.) compose on top of it.

## Colour tables

### Default

**Background**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `theme-primary-05` | `background-tint-01` | `transparent` | `transparent` |
| **Hover / Transient** | `theme-primary-04` | `background-tint-02` | `background-tint-02` | `background-tint-00` |
| **Active** | `theme-primary-06` | `background-tint-00` | `background-tint-00` | `background-tint-00` |
| **Disabled** | `background-neutral-04` | `background-neutral-03` | `transparent` + `opacity-50` | `transparent` + `opacity-50` |

**Foreground**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `text-inverted-05` | `text-03` | `text-03` | `text-03` |
| **Hover / Transient** | `text-inverted-05` | `text-04` | `text-04` | `text-04` |
| **Active** | `text-inverted-05` | `text-05` | `text-05` | `text-05` |
| **Disabled** | `text-inverted-04` | `text-01` | `text-01` | `text-01` |

### Action

**Background**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `action-link-05` | `background-tint-01` | `transparent` | `transparent` |
| **Hover / Transient** | `action-link-04` | `background-tint-02` | `background-tint-02` | `background-tint-00` |
| **Active** | `action-link-06` | `background-tint-00` | `background-tint-00` | `background-tint-00` |
| **Disabled** | `action-link-02` | `background-neutral-02` | `transparent` + `opacity-50` | `transparent` + `opacity-50` |

**Foreground**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `text-light-05` | `action-text-link-05` | `action-text-link-05` | `action-text-link-05` |
| **Hover / Transient** | `text-light-05` | `action-text-link-05` | `action-text-link-05` | `action-text-link-05` |
| **Active** | `text-light-05` | `action-text-link-05` | `action-text-link-05` | `action-text-link-05` |
| **Disabled** | `text-01` | `action-link-03` | `action-link-03` | `action-link-03` |

### Danger

**Background**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `action-danger-05` | `background-tint-01` | `transparent` | `transparent` |
| **Hover / Transient** | `action-danger-04` | `background-tint-02` | `background-tint-02` | `background-tint-00` |
| **Active** | `action-danger-06` | `background-tint-00` | `background-tint-00` | `background-tint-00` |
| **Disabled** | `action-danger-02` | `background-neutral-02` | `transparent` + `opacity-50` | `transparent` + `opacity-50` |

**Foreground**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `text-light-05` | `action-text-danger-05` | `action-text-danger-05` | `action-text-danger-05` |
| **Hover / Transient** | `text-light-05` | `action-text-danger-05` | `action-text-danger-05` | `action-text-danger-05` |
| **Active** | `text-light-05` | `action-text-danger-05` | `action-text-danger-05` | `action-text-danger-05` |
| **Disabled** | `text-01` | `action-danger-03` | `action-danger-03` | `action-danger-03` |

### Select (unselected)

**Background**

| | Light | Heavy |
|---|---|---|
| **Rest** | `transparent` | `transparent` |
| **Hover / Transient** | `background-tint-02` | `background-tint-02` |
| **Active** | `background-neutral-00` | `background-neutral-00` |
| **Disabled** | `transparent` | `transparent` |

**Foreground**

| | Light | Heavy |
|---|---|---|
| **Rest** | `text-04` (icon: `text-03`) | `text-04` (icon: `text-03`) |
| **Hover / Transient** | `text-04` | `text-04` |
| **Active** | `text-05` | `text-05` |
| **Disabled** | `text-02` | `text-02` |

### Select (selected)

**Background**

| | Light | Heavy |
|---|---|---|
| **Rest** | `transparent` | `action-link-01` |
| **Hover / Transient** | `background-tint-02` | `background-tint-02` |
| **Active** | `background-neutral-00` | `background-tint-00` |
| **Disabled** | `transparent` | `transparent` |

**Foreground**

| | Light | Heavy |
|---|---|---|
| **Rest** | `action-link-05` | `action-link-05` |
| **Hover / Transient** | `action-link-05` | `action-link-05` |
| **Active** | `action-link-05` | `action-link-05` |
| **Disabled** | `action-link-03` | `action-link-03` |

### Sidebar (unselected)

> No CSS `:active` state — only hover/transient and selected.

**Background**

| | Light |
|---|---|
| **Rest** | `transparent` |
| **Hover / Transient** | `background-tint-03` |
| **Disabled** | `transparent` |

**Foreground**

| | Light |
|---|---|
| **Rest** | `text-03` |
| **Hover / Transient** | `text-04` |
| **Disabled** | `text-01` |

### Sidebar (selected)

> Completely static — hover and transient have no effect.

**Background**

| | Light |
|---|---|
| **All states** | `background-tint-00` |
| **Disabled** | `transparent` |

**Foreground**

| | Light |
|---|---|
| **All states** | `text-03` (icon: `text-02`) |
| **Disabled** | `text-01` |

## Sub-components

| Sub-component | Role |
|---|---|
| `Interactive.Base` | Applies the `.interactive` CSS class and data-attributes for variant and transient states via Radix Slot. |
| `Interactive.Container` | Structural `<div>` (or `<button>` / `<a>`) with flex layout, border, padding, rounding, and height variant presets. |

## Interactive.Base Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `variant` | `"default" \| "action" \| "danger" \| "select" \| "sidebar" \| "none"` | `"default"` | Visual variant. Determines colour table used. `"none"` disables all background/foreground styling. |
| `prominence` | Depends on `variant` (see below) | Depends on `variant` | Visual weight within the variant. |
| `selected` | `boolean` | — | Only for `"select"` and `"sidebar"` variants. Switches foreground to action-link colours (select) or active-item state (sidebar). |
| `group` | `string` | — | Tailwind group class (e.g. `"group/Card"`) for `group-hover:*` utilities on descendants. |
| `transient` | `boolean` | `false` | Forces the hover visual state regardless of actual pointer state. |
| `href` | `string` | — | URL to navigate to. Passed through Slot to the child (Container renders an `<a>`). |
| `target` | `string` | — | Link target (e.g. `"_blank"`). Only used when `href` is provided. |
| `onClick` | `MouseEventHandler<HTMLElement>` | — | Click handler. Blocked when disabled. |
| `ref` | `React.Ref<HTMLElement>` | — | Ref forwarded to the underlying element via Radix Slot. |

### Variant → Prominence mapping

| `variant` | Allowed `prominence` | Default prominence |
|---|---|---|
| `"default"` | `"primary" \| "secondary" \| "tertiary" \| "internal"` | `"primary"` |
| `"action"` | `"primary" \| "secondary" \| "tertiary" \| "internal"` | `"primary"` |
| `"danger"` | `"primary" \| "secondary" \| "tertiary" \| "internal"` | `"primary"` |
| `"select"` | `"light" \| "heavy"` | `"light"` |
| `"sidebar"` | `"light"` | `"light"` |
| `"none"` | *(not accepted)* | — |

## Interactive.Container Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `type` | `"submit" \| "button" \| "reset"` | — | When provided, renders a `<button>` instead of a `<div>`. Mutually exclusive with `href` from Base. |
| `border` | `boolean` | `false` | Applies a 1px border using the theme's border colour. |
| `roundingVariant` | `"default" \| "compact" \| "mini"` | `"default"` | Border-radius preset (see table below). |
| `heightVariant` | `SizeVariant` | `"lg"` | Height, min-width, and padding preset from the shared `SizeVariant` scale. |
| `widthVariant` | `WidthVariant` | `"auto"` | `"auto"` shrink-wraps, `"full"` stretches to fill parent. |
| `ref` | `React.Ref<HTMLElement>` | — | Ref forwarded to the root element (`<div>`, `<button>`, or `<a>`). |

### `roundingVariant` reference

| Value | Class | Radius |
|---|---|---|
| `"default"` | `rounded-12` | 0.75rem (12px) |
| `"compact"` | `rounded-08` | 0.5rem (8px) |
| `"mini"` | `rounded-04` | 0.25rem (4px) |

## Foreground colour (`--interactive-foreground`)

Each variant+prominence combination sets a `--interactive-foreground` CSS custom property that cascades to all descendants. The variable updates automatically across hover, active, and disabled states.

**Buy-in:** Descendants opt in to parent-controlled text colour by referencing the variable. Elements that don't reference it are unaffected — the variable is inert unless consumed.

```css
/* Utility class for plain elements */
.interactive-foreground {
  color: var(--interactive-foreground);
}
```

```tsx
// Future Text component — `interactive` prop triggers buy-in
<Interactive.Base variant="action" prominence="tertiary" onClick={handleClick}>
  <Interactive.Container>
    <Text interactive>Reacts to hover/active/disabled</Text>
    <Text color="text03">Stays static</Text>
  </Interactive.Container>
</Interactive.Base>
```

This is selective — component authors decide per-instance which text responds to interactivity. For example, a `LineItem` might opt in its title but not its description.

## Style invariants

The following invariants hold across all variant+prominence combinations:

1. For each variant, **secondary and tertiary rows are identical** (e.g. `default+secondary` = `default+tertiary` across all states).
2. **Hover and transient (`data-transient`) columns are always equal** (both background and foreground) for non-select variants. CSS `:active` is also equal to hover/transient for all rows *except* `default+secondary` and `default+tertiary`, where foreground progressively darkens (`text-03` -> `text-04` -> `text-05`) and `:active` uses a distinct background (`tint-00` instead of `tint-02`). For the `select` variant, `data-transient` forces hover background while `data-selected` independently controls the action-link foreground colours.
3. **`action+primary` and `danger+primary` are row-wise identical** (both use `--text-light-05` / `--text-01`).
4. **`action+secondary`/`tertiary` and `danger+secondary`/`tertiary` are structurally identical** — only the colour family differs (`link` [blue] vs `danger` [red]).
5. **`internal` is similar to `tertiary`** but uses a subtler hover background (`tint-00` instead of `tint-02`).
