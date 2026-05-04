# CreateButton

**Import:** `import { CreateButton } from "@opal/components";`

A very thin wrapper over [`Button`](../button/README.md). It fixes two things and nothing else:

1. **Icon** — always `SvgPlusCircle` on the left.
2. **Default prominence** — `"secondary"` instead of `Button`'s default `"primary"`.

Every other `Button` prop passes straight through. If you need a different icon, use `Button` directly.

## Props

Identical to [`ButtonProps`](../button/README.md#props), minus `icon`.

| Prop | Default | Notes |
|------|---------|-------|
| `children` | `"Create"` | Falls back to the string `"Create"` when omitted |
| `prominence` | `"secondary"` | Override with any `Button` prominence value |

## Usage

```tsx
import { CreateButton } from "@opal/components";

// Default — renders "Create" with SvgPlusCircle, secondary prominence
<CreateButton onClick={handleCreate} />

// Custom label
<CreateButton onClick={handleCreate}>New Document</CreateButton>

// Override prominence
<CreateButton prominence="tertiary" onClick={handleCreate}>Add</CreateButton>

// As a link
<CreateButton href="/admin/new">New Item</CreateButton>
```
