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

## Sub-components

| Sub-component | Role |
|---|---|
| `Interactive.Base` | Applies the `.interactive` CSS class and data-attributes for variant and transient states via Radix Slot. |
| `Interactive.Container` | Structural `<div>` with flex layout, border, padding, rounding, and height variant presets. |

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
