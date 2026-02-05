# Core

The lowest-level primitives of the Opal design system. Think of `core` like Rust's `core` crate — compiler intrinsics and foundational types — while higher-level modules (like Rust's `std`) provide the public-facing components that most consumers should reach for first.

End-users *can* use these components directly when needed, but in most cases they should prefer the higher-level components (such as `Button`, `IconButton`, `FilterButton`, etc.) that are built on top of `core`.

## Contents

### Interactive

Our interactive components (`Button`, `FilterButton`, `IconButton`, etc.) currently each define their own styling for primary, secondary, and tertiary hover/active/pressed states — a lot of duplicated CSS and logic.

`Interactive` is the foundational layer that unifies this. It defines what the design language dictates for hover, active, disabled, and pressed states in a single place. Higher-level components compose on top of it rather than re-implementing interaction styling independently.

| Sub-component | Role |
|---|---|
| `Interactive.Base` | Applies the `.interactive` CSS class and data-attributes for variant, hover-disable, and pressed states via Radix Slot. |
| `Interactive.Container` | Structural `<div>` with border, padding, rounding, and height variant presets. |
| `Interactive.ChevronContainer` | `Container` with a chevron icon that rotates when open (for popover triggers, dropdowns, etc.). |
