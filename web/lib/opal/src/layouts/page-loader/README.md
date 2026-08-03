# PageLoader

**Import:** `import { PageLoader } from "@opal/layouts";`

The full-page loading state: the animated `OnyxLoader` mark centered with a label beneath. This is a layout: it arranges `OnyxLoader` and a `Text` label into a centered stack.

Use it for page and route-level loading. For an inline or section-level loader without a label, use `OnyxLoader` from `@opal/components` directly.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `text` | `string \| RichStr` | `"Loading …"` | Label beneath the mark. Pass `markdown()` for inline markdown |

## Usage

```tsx
import { PageLoader } from "@opal/layouts";

if (isLoading) return <PageLoader />;

// Custom label
<PageLoader text="Fetching documents …" />;
```
