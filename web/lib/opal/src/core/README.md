# Core

The lowest-level primitives of the Opal design system. Think of `core` like Rust's `core` crate — compiler intrinsics and foundational types — while higher-level modules (like Rust's `std`) provide the public-facing components that most consumers should reach for first.

End-users *can* use these components directly when needed, but in most cases they should prefer the higher-level components (such as `Button`, `IconButton`, `FilterButton`, etc.) that are built on top of `core`.

## Contents

### Interactive

Our interactive components (`Button`, `FilterButton`, `IconButton`, etc.) currently each define their own styling for primary, secondary, and tertiary hover/active/selected states — a lot of duplicated CSS and logic.

`Interactive` is the foundational layer that unifies this. It defines what the design language dictates for hover, active, disabled, and selected states in a single place. Higher-level components compose on top of it rather than re-implementing interaction styling independently.

| Sub-component | Role |
|---|---|
| `Interactive.Base` | Applies the `.interactive` CSS class and data-attributes for variant, hover-disable, and active states via Radix Slot. |
| `Interactive.Container` | Structural `<div>` with border, padding, rounding, and height variant presets. |
| `Interactive.ChevronContainer` | `Container` with a chevron icon that rotates when open (for popover triggers, dropdowns, etc.). |

#### Foreground colour (`--interactive-foreground`)

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

The following invariants hold across all combinations:

1. For each variant, **secondary and ghost rows are identical** (e.g. `default+secondary` ≡ `default+ghost` across all states).
2. **Hover and selected (`data-selected`) columns are always equal** (both background and foreground). CSS `:active` is also equal to hover/selected for all rows *except* `default+secondary` and `default+ghost`, where foreground progressively darkens (`text-03` → `text-04` → `text-05`) and `:active` uses a distinct background (`tint-00` instead of `tint-02`).
3. **`action+primary` and `danger+primary` are row-wise identical** (both use `--text-light-05` / `--text-01`).
4. **`action+secondary`/`ghost` and `danger+secondary`/`ghost` are structurally identical** — only the colour family differs (`link` [blue] vs `danger` [red]).
