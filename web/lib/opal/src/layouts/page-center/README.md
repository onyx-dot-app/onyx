# PageCenter

**Import:** `import { PageCenter } from "@opal/layouts";`

Centres its children in the page body, both horizontally and vertically. Use it for states that replace a whole page body: loading, errors, empty pages.

The frame is full width and at least 60% of the viewport tall (`min-h-[60vh]`). A percentage height such as `h-full` does not work here, because the settings page body has no set height; a viewport-based minimum does.

## Props

| Prop       | Type        | Default        | Description                     |
| ---------- | ----------- | -------------- | ------------------------------- |
| `children` | `ReactNode` | **(required)** | The content to centre.          |

## Usage

```tsx
import { IllustrationContent, PageCenter } from "@opal/layouts";
import { SvgPlugBroken } from "@opal/illustrations";

<PageCenter>
  <IllustrationContent
    illustration={SvgPlugBroken}
    title="Couldn't load your credentials"
  />
</PageCenter>;
```

`PageLoader` from `@opal/loaders` is built on it.
