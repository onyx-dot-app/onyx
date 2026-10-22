# StickyBox

**Import:** `import { StickyBox } from "@opal/layouts";`

A block that pins to the top or bottom of its scroll container as the page scrolls past it. It sits on the `--z-sticky` level, above content and above a page's `z-10` details such as tab underlines, and below the settings header.

## Usage

```tsx
<StickyBox stick="top" inset={2} active={hasChanges} shadow>
  <MessageCard variant="warning" title="Changes require a re-index." />
</StickyBox>
```

## Props

| Prop       | Type                | Default | Description                                                                                      |
| ---------- | ------------------- | ------- | ------------------------------------------------------------------------------------------------ |
| `stick`    | `"top" \| "bottom"` | `"top"` | The edge of the scroll container the box pins to                                                 |
| `inset`    | `Spacing`           | `0`     | Gap kept from that edge while pinned, as a spacing step (`N / 4` rem)                            |
| `active`   | `boolean`           | `true`  | Whether the box sticks at all; off, it is a plain block in the flow                              |
| `shadow`   | `boolean`           | `false` | Cast a shadow while pinned; it follows the shape of the content, so a rounded card stays rounded |
| `children` | `ReactNode`         | —       | What pins                                                                                        |
| `ref`      | `Ref<HTMLDivElement>` | —     | Ref forwarded to the root `<div>`                                                                |

## Behaviour

- **Pinned state.** CSS has no "is pinned" state, so with `shadow` the box watches itself with an `IntersectionObserver` rooted at the nearest scrolling ancestor. Fully visible, it is in the flow; once its pinned edge sits on the container's edge plus the inset, it is pinned and the root carries `data-stuck`, which a consumer can style off too.
- **The gap is transparent.** Nothing is painted outside the content. A painted band would show square corners around a rounded card over whatever scrolls beneath.
- **Constraint.** `position: sticky` needs the scroll container to be an ancestor with no `overflow: hidden` between the two. `SettingsLayouts.Root` qualifies; the box cannot fix a layout that does not.
