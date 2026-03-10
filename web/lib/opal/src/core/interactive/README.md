# Interactive

The foundational layer for all clickable surfaces in the design system. Defines hover, active, disabled, and interaction-override state styling in a single place. Higher-level components (Button, SelectButton, OpenButton, etc.) compose on top of it.

## Sub-components

| Sub-component | Role | Docs |
|---|---|---|
| `Interactive.Stateless` | Stateless surfaces (buttons, links, cards). Variant × prominence color matrix. | [README](./stateless/README.md) |
| `Interactive.Stateful` | Stateful surfaces (toggles, sidebar items). Variant × state color matrix. | [README](./stateful/README.md) |
| `Interactive.Container` | Structural box with height, rounding, padding, and optional border. Shared by both. | [README](./container/README.md) |
| `Interactive.Foldable` | Zero-width collapsible wrapper with CSS grid animation. | [README](./foldable/README.md) |

## Foreground colour system

Each variant/prominence/state combination sets two CSS custom properties:
- `--interactive-foreground` — text color
- `--interactive-foreground-icon` — icon color

Both are registered via `@property` as `<color>` in `shared.css`, enabling the browser to interpolate them directly on the parent `.interactive` element. Children read the variables with no independent transitions, guaranteeing perfect sync.

**Opt-in classes:**
- `.interactive-foreground` — sets `color: var(--interactive-foreground)`
- `.interactive-foreground-icon` — sets `color: var(--interactive-foreground-icon)`

## Interaction override

Both `Stateless` and `Stateful` support `interaction?: "rest" | "hover" | "active"` for JS-controlled visual state overrides via `data-interaction`.

## Colour tables

### Stateless: Default

**Background**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `theme-primary-05` | `background-tint-01` | `transparent` | `transparent` |
| **Hover** | `theme-primary-04` | `background-tint-02` | `background-tint-02` | `background-tint-00` |
| **Active** | `theme-primary-06` | `background-tint-00` | `background-tint-00` | `background-tint-00` |
| **Disabled** | `background-neutral-04` | `background-neutral-03` | `transparent` | `transparent` |

**Foreground**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `text-inverted-05` | `text-03` | `text-03` | `text-03` |
| **Hover** | `text-inverted-05` | `text-04` | `text-04` | `text-04` |
| **Active** | `text-inverted-05` | `text-05` | `text-05` | `text-05` |
| **Disabled** | `text-inverted-04` | `text-01` | `text-01` | `text-01` |

### Stateless: Action

**Background**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `action-link-05` | `background-tint-01` | `transparent` | `transparent` |
| **Hover** | `action-link-04` | `background-tint-02` | `background-tint-02` | `background-tint-00` |
| **Active** | `action-link-06` | `background-tint-00` | `background-tint-00` | `background-tint-00` |
| **Disabled** | `action-link-02` | `background-neutral-02` | `transparent` | `transparent` |

**Foreground**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `text-light-05` | `action-text-link-05` | `action-text-link-05` | `action-text-link-05` |
| **Hover** | `text-light-05` | `action-text-link-05` | `action-text-link-05` | `action-text-link-05` |
| **Active** | `text-light-05` | `action-text-link-05` | `action-text-link-05` | `action-text-link-05` |
| **Disabled** | `text-01` | `action-link-03` | `action-link-03` | `action-link-03` |

### Stateless: Danger

**Background**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `action-danger-05` | `background-tint-01` | `transparent` | `transparent` |
| **Hover** | `action-danger-04` | `background-tint-02` | `background-tint-02` | `background-tint-00` |
| **Active** | `action-danger-06` | `background-tint-00` | `background-tint-00` | `background-tint-00` |
| **Disabled** | `action-danger-02` | `background-neutral-02` | `transparent` | `transparent` |

**Foreground**

| | Primary | Secondary | Tertiary | Internal |
|---|---|---|---|---|
| **Rest** | `text-light-05` | `action-text-danger-05` | `action-text-danger-05` | `action-text-danger-05` |
| **Hover** | `text-light-05` | `action-text-danger-05` | `action-text-danger-05` | `action-text-danger-05` |
| **Active** | `text-light-05` | `action-text-danger-05` | `action-text-danger-05` | `action-text-danger-05` |
| **Disabled** | `text-01` | `action-danger-03` | `action-danger-03` | `action-danger-03` |

### Stateful: Select-Heavy / Select-Light

**Background (empty/filled)**

| | Select-Heavy | Select-Light |
|---|---|---|
| **Rest** | `transparent` | `transparent` |
| **Hover** | `background-tint-02` | `background-tint-02` |
| **Active** | `background-neutral-00` | `background-neutral-00` |
| **Disabled** | `transparent` | `transparent` |

**Background (selected)**

| | Select-Heavy | Select-Light |
|---|---|---|
| **Rest** | `action-link-01` | `transparent` |
| **Hover** | `background-tint-02` | `background-tint-02` |
| **Active** | `background-tint-00` | `background-tint-00` |
| **Disabled** | `transparent` | `transparent` |

**Foreground (empty)**

| | Text | Icon |
|---|---|---|
| **Rest** | `text-04` | `text-03` |
| **Hover** | `text-04` | `text-04` |
| **Active** | `text-05` | `text-05` |
| **Disabled** | `text-01` | `text-01` |

**Foreground (selected)**

| | Text | Icon |
|---|---|---|
| **Rest** | `action-link-05` | `action-link-05` |
| **Hover** | `action-link-05` | `action-link-05` |
| **Active** | `action-link-05` | `action-link-05` |
| **Disabled** | `action-link-03` | `action-link-03` |

### Stateful: Sidebar

**Background**

| | Empty/Filled | Selected |
|---|---|---|
| **Rest** | `transparent` | `background-tint-00` |
| **Hover** | `background-tint-03` | `background-tint-03` |
