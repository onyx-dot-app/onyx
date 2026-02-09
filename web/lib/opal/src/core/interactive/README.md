# Interactive

The foundational layer for all clickable surfaces in the design system. Defines hover, active, disabled, and selected state styling in a single place. Higher-level components (Button, OpenButton, etc.) compose on top of it.

## Sub-components

| Sub-component | Role |
|---|---|
| `Interactive.Base` | Applies the `.interactive` CSS class and data-attributes for variant, hover-disable, and selected states via Radix Slot. |
| `Interactive.Container` | Structural `<div>` with flex layout, border, padding, rounding, and height variant presets. |

## Foreground colour (`--interactive-foreground`)

Each variant+subvariant combination sets a `--interactive-foreground` CSS custom property that cascades to all descendants. The variable updates automatically across hover, active, and disabled states.

**Buy-in:** Descendants opt in to parent-controlled text colour by referencing the variable. Elements that don't reference it are unaffected — the variable is inert unless consumed.

```css
/* Utility class for plain elements */
.interactive-foreground {
  color: var(--interactive-foreground);
}
```

```tsx
// Future Text component — `interactive` prop triggers buy-in
<Interactive.Base variant="action" subvariant="ghost" onClick={handleClick}>
  <Interactive.Container>
    <Text interactive>Reacts to hover/active/disabled</Text>
    <Text color="text03">Stays static</Text>
  </Interactive.Container>
</Interactive.Base>
```

This is selective — component authors decide per-instance which text responds to interactivity. For example, a `LineItem` might opt in its title but not its description.

## Style invariants

The following invariants hold across all variant+subvariant combinations:

1. For each variant, **secondary and ghost rows are identical** (e.g. `default+secondary` = `default+ghost` across all states).
2. **Hover and selected (`data-selected`) columns are always equal** (both background and foreground). CSS `:active` is also equal to hover/selected for all rows *except* `default+secondary` and `default+ghost`, where foreground progressively darkens (`text-03` -> `text-04` -> `text-05`) and `:active` uses a distinct background (`tint-00` instead of `tint-02`).
3. **`action+primary` and `danger+primary` are row-wise identical** (both use `--text-light-05` / `--text-01`).
4. **`action+secondary`/`ghost` and `danger+secondary`/`ghost` are structurally identical** — only the colour family differs (`link` [blue] vs `danger` [red]).
