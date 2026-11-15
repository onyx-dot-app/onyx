# EndOfList

**Import:** `import { EndOfList } from "@opal/components";`

A centered label flanked by two horizontal divider lines. Use to visually separate two sections
of a list or form flow (e.g. an "or" between an SSO button and an email/password form).

## Props

| Prop                   | Type                                | Default        | Description                                                         |
| ---------------------- | ----------------------------------- | -------------- | ------------------------------------------------------------------- |
| `title`                | `string \| RichStr`                 | **(required)** | Label rendered between the two dividers                             |
| `paddingParallel`      | `0 \| 0.5 \| 1 \| 2 \| 3 \| 4 \| 6` | `0`            | Inset along the lines, as a spacing step (`N / 4` rem), as on `Divider` |
| `paddingPerpendicular` | `0 \| 0.5 \| 1 \| 2 \| 3 \| 4 \| 6` | `0`            | Inset across the lines, as a spacing step (`N / 4` rem), as on `Divider` |

## Usage Examples

```tsx
import { EndOfList } from "@opal/components";
import { markdown } from "@opal/utils";

// Plain string
<EndOfList title="or" />

// Markdown
<EndOfList title={markdown("*or* sign in with SSO")} />

// Inset: 1rem along the lines, 0.5rem above and below
<EndOfList title="End of list" paddingParallel={4} paddingPerpendicular={2} />
```
