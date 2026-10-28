# Presence

**Import:** `import { Presence } from "@opal/components";`

Animates content in when it appears and out when it goes. It paints nothing of
its own (no border, background or padding). `SettingsLayouts.Body` uses it by
default (see `SettingsLayouts.Root`'s `animateEnter` prop), so the body of
every settings-style page arrives through it.

## Props

| Prop       | Type                                          | Default        | Description                                                             |
| ---------- | --------------------------------------------- | -------------- | ----------------------------------------------------------------------- |
| `show`     | `boolean`                                     | `true`         | Whether the content is present. `false` plays the exit, then removes it |
| `from`     | `"below"` \| `"end"` \| `"start"` \| `"none"` | `"below"`      | Where the content enters from                                           |
| `to`       | `"below"` \| `"end"` \| `"start"` \| `"none"` | same as `from` | Where the content leaves to                                             |
| `grow`     | `boolean`                                     | `false`        | Open the height before the entry and close it after the exit            |
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
