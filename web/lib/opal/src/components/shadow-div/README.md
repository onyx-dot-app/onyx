# ShadowDiv

**Import:** `import { ShadowDiv } from "@opal/components";`

A scrollable container with automatic top/bottom shadow indicators. Gradients fade in when the
content scrolls past the visible region, signaling that more content exists in that direction.

## Props

| Prop                 | Type                                | Default                        | Description                                   |
| -------------------- | ----------------------------------- | ------------------------------ | --------------------------------------------- |
| `backgroundColor`    | `string`                            | `var(--background-neutral-00)` | Color used for the shadow gradients           |
| `shadowHeight`       | `string`                            | `"1.5rem"`                     | Height of each gradient                       |
| `scrollContainerRef` | `RefObject<HTMLDivElement \| null>` | —                              | External ref for programmatic scrolling       |
| `bottomOnly`         | `boolean`                           | `false`                        | Show only the bottom gradient                 |
| `topOnly`            | `boolean`                           | `false`                        | Show only the top gradient                    |
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
<ShadowDiv bottomOnly className="max-h-[20rem]">
  <div>Content...</div>
</ShadowDiv>

// External scroll ref
const scrollRef = useRef<HTMLDivElement>(null);
<ShadowDiv scrollContainerRef={scrollRef} className="max-h-[15rem]">
  <ListItems />
</ShadowDiv>
```
