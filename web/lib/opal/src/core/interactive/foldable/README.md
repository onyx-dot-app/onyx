# Interactive.Foldable

**Import:** `import { Interactive } from "@opal/core";` — use as `Interactive.Foldable`.

A zero-width collapsible wrapper that expands when its ancestor `.interactive` element is hovered or has an interaction override. Uses a CSS grid `0fr → 1fr` animation for smooth expand/collapse.

## Requirements

- Must be placed inside an `Interactive.Stateless` or `Interactive.Stateful` tree.
- The direct parent element should add the `interactive-foldable-host` class for synchronized gap transitions.

## Props

| Prop | Type | Description |
|------|------|-------------|
| `children` | `ReactNode` | Content that folds/unfolds |

## CSS triggers

The foldable expands when any of these conditions are met on an ancestor `.interactive`:
- `:hover` pseudo-class
- `data-interaction="hover"`
- `data-interaction="active"`

## Usage

```tsx
<Interactive.Stateful variant="select-heavy" state="empty">
  <Interactive.Container>
    <div className="interactive-foldable-host flex items-center">
      <Icon />
      <Interactive.Foldable>
        <span>Label text</span>
      </Interactive.Foldable>
    </div>
  </Interactive.Container>
</Interactive.Stateful>
```
