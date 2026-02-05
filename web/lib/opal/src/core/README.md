# Core

Internal building blocks of the Opal design system. These are the lowest-level UI primitives — they carry no business logic and express only structural or stylistic concerns (layout, spacing, color variants, interaction states).

**These components are not intended for direct use by end-users.** They exist so that higher-level, public-facing components (such as `Button`, `Card`, `Popover`, etc.) can be composed from them without duplicating behavior.

## Contents

| Component | Purpose |
|---|---|
| `Interactive` | Compound component (`Base`, `Container`, `ChevronContainer`) that provides hover/active/pressed states and structural containers for any clickable surface. |
