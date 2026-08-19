# EndOfList

**Import:** `import { EndOfList } from "@opal/components";`

A centered label flanked by two horizontal divider lines. Use to visually separate two sections
of a list or form flow (e.g. an "or" between an SSO button and an email/password form).

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `title` | `string \| RichStr` | **(required)** | Label rendered between the two dividers |

## Usage Examples

```tsx
import { EndOfList } from "@opal/components";
import { markdown } from "@opal/utils";

// Plain string
<EndOfList title="or" />

// Markdown
<EndOfList title={markdown("*or* sign in with SSO")} />
```
