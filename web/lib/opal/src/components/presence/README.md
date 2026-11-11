# Presence

**Import:** `import { Presence } from "@opal/components";`

Animates content in when it appears and out when it goes. `Presence.Swap`
replaces one piece of content with another through the same exit and entry.
Neither paints anything of its own (no border, background or padding). `SettingsLayouts.Body` uses it by
default (see `SettingsLayouts.Root`'s `animateEnter` prop), so the body of
every settings-style page arrives through it.

## Props

| Prop       | Type                                          | Default        | Description                                                             |
| ---------- | --------------------------------------------- | -------------- | ----------------------------------------------------------------------- |
| `show`     | `boolean`                                     | `true`         | Whether the content is present. `false` plays the exit, then removes it |
| `from`     | `"below"` \| `"end"` \| `"start"` \| `"none"` | `"below"`      | Where the content enters from                                           |
| `to`       | `"below"` \| `"end"` \| `"start"` \| `"none"` | same as `from` | Where the content leaves to                                             |
| `appear`   | `boolean`                                     | `true`         | Play the entry when the content is present on mount                     |
| `grow`     | `boolean`                                     | `false`        | Open the height before the entry and close it after the exit            |
| `onExited` | `() => void`                                  | —              | Called once the exit has finished and the content is gone               |
| `width`    | `ExtremaSizeVariants`                         | `"full"`       | Width preset                                                            |
| `height`   | `ExtremaSizeVariants`                         | —              | Height preset. Unset, no height class is applied                        |
| `ref`      | `Ref<HTMLDivElement>`                         | —              | Ref forwarded to the root `<div>`                                       |
| `children` | `ReactNode`                                   | —              | The content that animates                                               |

## Behaviour

- **Entry:** the content fades in (opacity 0 to 1) while it moves 8px from
  `from`, over 250ms, ease-out. `below` rises from below; `end` and `start`
  come in sideways; `none` only fades.
- **Exit:** when `show` changes to `false`, the content fades out while it
  moves 8px toward `to`, over 200ms, ease-in. Then `Presence` renders nothing.
  The leaving content is `inert`.
- `to` defaults to `from`, so the content leaves the way it came. Set a
  different `to` for carousel motion, e.g. `from="end" to="start"`.
- `end` and `start` follow the text direction: they mirror in right-to-left
  text.
- **`grow`:** before the entry, the height opens from zero over 200ms, and the
  content stays invisible until it has. After the exit, the height closes to
  zero before the content is removed. Use it so the content around it moves
  aside smoothly.
- Mounting with `show={false}` renders nothing, with no animation.
- `appear={false}` shows content that is present on mount at once. Later
  changes of `show` still animate.
- `onExited` fires in the same update that removes the content, so a parent
  can render what comes next without a frame of empty space. With reduced
  motion it fires right after the content goes.
- Without `show`, the entry plays once, on mount. To play it again, change the
  `key` (e.g. to the route or a view counter). React then mounts a new root.
- Reduced motion turns the animations and the `grow` transition off: the
  content appears and goes at once.
- While the entry runs, the root has a `transform`, so a `position: fixed`
  descendant is positioned against it for those 250ms. Portaled overlays
  (modals, popovers) are not affected.
- Give it `height="full"` when the content relies on a full-height parent, such
  as a page with its own scroll container.

## Usage

```tsx
import { Presence } from "@opal/components";

// Once per route
<Presence key={pathname} height="full">
  {page}
</Presence>;

// Shown and hidden, entering and leaving from the inline end
<Presence show={hasPrevious} from="end" width="fit">
  <BackButton />
</Presence>;
```

## Presence.Swap

Replaces one piece of content with another, like a carousel step or a button
whose label changes. Use it when a slot changes its content. Use `Presence`
when content appears or leaves.

| Prop        | Type                  | Default     | Description                             |
| ----------- | --------------------- | ----------- | --------------------------------------- |
| `swapKey`   | `React.Key`           | —           | Identity of the content. A change swaps |
| `direction` | `"forward" \| "back"` | `"forward"` | Which way the content moves on a swap   |
| `axis`      | `"block" \| "inline"` | `"block"`   | Which size follows the content          |
| `children`  | `ReactNode`           | —           | The content for the current `swapKey`   |

A change of `swapKey` plays three phases, one after the other:

1. **Out:** the old content plays the `Presence` exit, toward the inline start
   (`forward`) or the inline end (`back`).
2. **Resize:** the box animates from the old height (or width, with
   `axis="inline"`) to the new content's, over 200ms. The new content waits,
   invisible, at the first frame of its entry. When the size does not change,
   this phase is skipped.
3. **In:** the new content plays the `Presence` entry, from the inline end
   (`forward`) or the inline start (`back`).

- The content present on mount shows at once, with no entry.
- A content change that keeps the same `swapKey` (for example, a list that
  finishes loading) resizes smoothly, with no fade.
- A new `swapKey` that arrives mid-swap does not restart the swap. The swap
  goes on and shows the newest content.
- On the block axis, the box clips only the height, so the sideways motion is
  not cut off. Give the scroll container around it some inline room (8px) if
  it clips on the inline axis. On the inline axis, the content keeps its own
  width and nothing clips.
- Reduced motion turns every phase off: the content changes at once.

```tsx
import { Presence } from "@opal/components";

<Presence.Swap swapKey={step} direction={isForward ? "forward" : "back"}>
  <StepCard step={step} />
</Presence.Swap>;

<Presence.Swap swapKey={isFinal ? "finish" : "next"} axis="inline">
  <Button>{label}</Button>
</Presence.Swap>;
```
