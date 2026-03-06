# Disabled

**Import:** `import { Disabled, useDisabled } from "@opal/core";`

The **single entry point** for disabling any opal component. No opal component exposes its own `disabled` prop — you always wrap with `<Disabled>`.

## Architecture

```
<Disabled disabled={expr}>          ← display: contents div, sets data-disabled + context
  └─ <Button type="submit">Save</Button>   ← reads useDisabled() for JS concerns
```

Two layers work together:

1. **CSS layer** — the `.opal-disabled[data-disabled] > *` selector applies baseline visuals (opacity, cursor, pointer-events) to all direct children. Any component can be disabled without opting in.

2. **JS layer** — `DisabledContext` provides `{ isDisabled, allowClick }`. Components that need JS-level disabled behaviour (e.g. `Interactive.Base` blocks `onClick` and `href`) consume this via the `useDisabled()` hook.

### Why a wrapper, not a prop?

- **Single responsibility:** disabled state lives in one place, not duplicated across every component's prop interface.
- **Composable:** wrap a single button, a form section, or an entire page. Works with any component — opal or otherwise.
- **Consistent:** baseline visuals are guaranteed. Components can layer on custom styling (like `Interactive.Base`'s per-variant disabled colours) without every component reimplementing the pattern.

### How `Interactive.Base` integrates

`Interactive.Base` calls `useDisabled()` internally:

- Sets `data-disabled` and `aria-disabled` on the underlying element (same CSS selectors as before).
- Blocks `onClick` and `href` when `isDisabled && !allowClick`.
- Adds `pointer-events: auto` to its own `[data-disabled]` rule, overriding the baseline `pointer-events: none`. This allows hover events to fire (for tooltips on disabled buttons) while JS handles click blocking.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `disabled` | `boolean` | `false` | Whether the children are disabled. |
| `allowClick` | `boolean` | `false` | When `true`, pointer events are **not** blocked — only visual styling is applied. Useful for tooltips on disabled elements. |
| `children` | `ReactNode` | **(required)** | Content to disable. |
| `ref` | `React.Ref<HTMLDivElement>` | — | Forwarded ref to the wrapper `<div>`. |

### Data attributes (set on the wrapper div)

| Attribute | When set | Purpose |
|-----------|----------|---------|
| `data-disabled` | `disabled` is truthy | Triggers baseline CSS; descendants can target for custom styling. |
| `data-allow-click` | `disabled && allowClick` | Overrides `pointer-events: none` so clicks pass through. |

## `useDisabled()` hook

```ts
const { isDisabled, allowClick } = useDisabled();
```

Returns the disabled state from the nearest `<Disabled>` ancestor. When no ancestor exists, returns `{ isDisabled: false, allowClick: false }`.

**When to use:** Component authors call this inside components that need JS-level disabled behaviour — blocking clicks, suppressing navigation, setting `aria-disabled`, rendering a native `disabled` attribute on `<button>`, etc.

**When NOT to use:** If a component only needs visual disabled styling (opacity + cursor), the baseline CSS handles it automatically — no hook needed.

## CSS

```css
/* Always present — no layout impact */
.opal-disabled { display: contents; }

/* Baseline disabled visuals on direct children */
.opal-disabled[data-disabled] > * {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
  user-select: none;
}

/* allowClick — let pointer events through */
.opal-disabled[data-disabled][data-allow-click] > * {
  pointer-events: auto;
}
```

Components that want custom disabled visuals (e.g. `Interactive.Base` uses per-variant background and foreground colours) override the baseline by:

1. Setting `pointer-events: auto` on their own `[data-disabled]` rule.
2. Using the existing variant CSS (e.g. `.interactive[data-disabled]` rules in `interactive/styles.css`).

This follows the same inert-unless-consumed pattern as `--interactive-foreground`.

## Usage

### Disable a single button

```tsx
import { Disabled } from "@opal/core";
import { Button } from "@opal/components";

<Disabled disabled={isSubmitting}>
  <Button type="submit">Save</Button>
</Disabled>
```

### Allow hover for tooltips on a disabled button

```tsx
<Disabled disabled={!canEdit} allowClick>
  <Button tooltip="Upgrade to edit" onClick={handleEdit}>Edit</Button>
</Disabled>
```

### Disable an entire section

```tsx
<Disabled disabled={!isEnabled}>
  <div>
    <InputTypeIn placeholder="Name" />
    <Button>Submit</Button>
  </div>
</Disabled>
```

### Nesting

`Disabled` wrappers can nest. The innermost wrapper wins for its subtree:

```tsx
<Disabled disabled>
  <div>
    <Button>Disabled</Button>
    <Disabled disabled={false}>
      <Button>Enabled (inner wrapper overrides)</Button>
    </Disabled>
  </div>
</Disabled>
```

## For component authors

If you are building a new opal component that needs to respond to disabled state:

1. **Do NOT add a `disabled` prop.** Consumers wrap with `<Disabled>` instead.
2. **Visual-only?** You're done — baseline CSS handles it.
3. **Need JS behaviour?** Call `useDisabled()` and use `isDisabled` / `allowClick` to block handlers, set `aria-disabled`, render native `disabled` on `<button>`, etc.
4. **Need custom disabled styling?** Add a `[data-disabled]` CSS rule on your component's class. Set `pointer-events: auto` if your component handles click blocking in JS.
