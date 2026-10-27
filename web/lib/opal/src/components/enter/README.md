# Enter

**Import:** `import { Enter } from "@opal/components";`

Animates its content in once, when it mounts. It paints nothing of its own (no
border, background or padding). `SettingsLayouts.Body` uses it by default (see
`SettingsLayouts.Root`'s `animateEnter` prop), so the body of every
settings-style page arrives through it.

## Props

| Prop       | Type                  | Default     | Description                                      |
| ---------- | --------------------- | ----------- | ------------------------------------------------ |
| `variant`  | `"fade-up"`           | `"fade-up"` | How the content arrives                          |
| `width`    | `ExtremaSizeVariants` | `"full"`    | Width preset                                     |
| `height`   | `ExtremaSizeVariants` | —           | Height preset. Unset, no height class is applied |
| `ref`      | `Ref<HTMLDivElement>` | —           | Ref forwarded to the root `<div>`                |
| `children` | `ReactNode`           | —           | The content that animates in                     |

## Behaviour

- `fade-up`: the content fades in (opacity 0 to 1) while it rises 8px, over
  250ms, ease-out.
- The animation plays when `Enter` mounts. To play it again, change its `key`,
  e.g. to the route or a view counter. React then mounts a new root.
- Reduced motion turns the animation off.
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
