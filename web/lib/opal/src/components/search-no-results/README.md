# SearchNoResults

**Import:** `import { SearchNoResults } from "@opal/components";`

The empty state for a search that matched nothing. It shows the "not found" illustration and
the shared "No items match that search" copy (translated through `OpalStrings`).

Use it only when a search query caused the empty list. A list that is empty without a search
needs its own empty state (for example `IllustrationContent` with `SvgEmpty`).

## Props

None.

## Usage Examples

```tsx
import { SearchNoResults } from "@opal/components";

{
  query && results.length === 0 && <SearchNoResults />;
}
```
