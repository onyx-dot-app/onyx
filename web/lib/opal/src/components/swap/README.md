# Swap

**Import:** `import { Swap } from "@opal/components";`

Swaps one piece of content for another, like a carousel step. It paints
nothing of its own (no border, background or padding).

## Props

| Prop        | Type                  | Default     | Description                             |
| ----------- | --------------------- | ----------- | --------------------------------------- |
| `swapKey`   | `React.Key`           | —           | Identity of the content. A change swaps |
| `direction` | `"forward" \| "back"` | `"forward"` | Which way the content moves on a swap   |
| `children`  | `ReactNode`           | —           | The content for the current `swapKey`   |

## Behaviour

A change of `swapKey` plays three phases, one after the other:

1. **Out:** the old content fades out while it moves 8px toward the inline
   start (`forward`) or the inline end (`back`), over 200ms.
2. **Resize:** the box animates from the old height to the new content's
   height, over 200ms. The new content is hidden while this runs. When the
   height does not change, this phase is skipped.
3. **In:** the new content fades in while it moves 8px from the inline end
   (`forward`) or the inline start (`back`), over 200ms.

- The directions follow the text direction, so they mirror in right-to-left
  text.
- A content change that keeps the same `swapKey` (for example, a list that
  finishes loading) resizes smoothly, with no fade.
- A new `swapKey` that arrives mid-swap does not restart the swap. The swap
  goes on and shows the newest content.
- The leaving content is `inert` and `aria-hidden` while it fades out.
- Reduced motion turns every phase off: the content changes at once.
- The box clips only on the block axis, so the sideways motion is not cut off.
  Give the scroll container around it some inline room (8px) if it clips on
  the inline axis.

## Usage

```tsx
import { Swap } from "@opal/components";

<Swap swapKey={step} direction={isForward ? "forward" : "back"}>
  <StepCard step={step} />
</Swap>;
```
