# Enter

**Import:** `import { Enter } from "@opal/components";`

Animates its content in once, when it mounts. It paints nothing of its own (no
border, background or padding). `SettingsLayouts.Body` uses it by default (see
`SettingsLayouts.Root`'s `animateEnter` prop), so the body of every
settings-style page arrives through it.

## Props

| Prop       | Type                                                    | Default     | Description                                          |
| ---------- | ------------------------------------------------------- | ----------- | ---------------------------------------------------- |
| `variant`  | `"fade-up"` \| `"fade-from-end"` \| `"fade-from-start"` | `"fade-up"` | How the content arrives                              |
| `grow`     | `boolean`                                               | `false`     | Open the height from zero before the content arrives |
| `width`    | `ExtremaSizeVariants`                                   | `"full"`    | Width preset                                         |
| `height`   | `ExtremaSizeVariants`                                   | —           | Height preset. Unset, no height class is applied     |
| `ref`      | `Ref<HTMLDivElement>`                                   | —           | Ref forwarded to the root `<div>`                    |
| `children` | `ReactNode`                                             | —           | The content that animates in                         |

## Behaviour

- `fade-up`: the content fades in (opacity 0 to 1) while it rises 8px, over
  250ms, ease-out.
- `fade-from-end`: the content fades in while it moves 8px from the inline end
  (from the right in left-to-right text, from the left in right-to-left text),
  over 250ms, ease-out.
  `fade-from-start` is the mirror: it moves in from the inline start. Use the
  pair for forward and backward steps.
- `grow`: the height first opens from zero over 200ms, then the variant plays.
  The content stays invisible while the height opens, so it makes room before
  it arrives. Use it for an item added to a list, so the items around it move
  aside first.
- The animation plays when `Enter` mounts. To play it again, change its `key`,
  e.g. to the route or a view counter. React then mounts a new root.
- Reduced motion turns the animation and the `grow` transition off.
- While the animation runs, the root has a `transform`, so a `position: fixed`
  descendant is positioned against it for those 250ms. Portaled overlays
  (modals, popovers) are not affected.
- Give it `height="full"` when the content relies on a full-height parent, such
  as a page with its own scroll container.

## Usage

```tsx
import { Enter } from "@opal/components";

// Once per route
<Enter key={pathname} height="full">
  {page}
</Enter>;

// Once per view change
<Enter key={viewChangeId}>{views[view]}</Enter>;
```
