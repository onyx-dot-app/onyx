# ShadowDiv

**Import:** `import { ShadowDiv } from "@opal/components";`

A scrollable container with automatic top/bottom shadow indicators. Gradients fade in when the
content scrolls past the visible region, signaling that more content exists in that direction.
The gradients use the translucent `shadow-dark-01` token, black in both themes, so they read as a shadow on any surface.

## Props

| Prop                 | Type                                | Default                        | Description                                   |
| -------------------- | ----------------------------------- | ------------------------------ | --------------------------------------------- |
| `shadowHeight`       | `Spacing`                           | `6`                            | Height of each gradient, as a spacing step (`N / 4` rem) |
| `scrollContainerRef` | `RefObject<HTMLDivElement \| null>` | —                              | External ref for programmatic scrolling       |
| `shadowDirection`    | `ShadowDirection`                   | `"top-and-bottom"`             | `"top-and-bottom"`, `"top-only"`, or `"bottom-only"` |
| `variant`            | `"shadow" \| "mask"`                | `"shadow"`                     | `"shadow"` paints translucent gradients over the content; `"mask"` fades the content itself, for surfaces a gradient could not match |
| `className`          | `string`                            | —                              | Classes applied to the inner scroll container |

All other `HTMLAttributes<HTMLDivElement>` props are forwarded to the inner scroll container.

## Usage

```tsx
import { ShadowDiv } from "@opal/components";

// Default — top + bottom shadows
<ShadowDiv className="max-h-[20rem]">
  <div>Long content...</div>
</ShadowDiv>

// Only bottom shadow
<ShadowDiv shadowDirection="bottom-only" className="max-h-[20rem]">
  <div>Content...</div>
</ShadowDiv>

// External scroll ref
const scrollRef = useRef<HTMLDivElement>(null);
<ShadowDiv scrollContainerRef={scrollRef} className="max-h-[15rem]">
  <ListItems />
</ShadowDiv>
```
