# MessageCard

**Import:** `import { MessageCard } from "@opal/components";`

A styled card for displaying messages, alerts, or status notifications. Uses `Content` internally
for consistent title/description/icon layout. Supports 5 variants with corresponding background
and border colors.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | `"default" \| "info" \| "success" \| "warning" \| "error"` | `"default"` | Visual variant (controls background, border, and icon) |
| `icon` | `IconFunctionComponent` | per variant | Override the default variant icon |
| `title` | `string \| RichStr` | — | Main title text |
| `description` | `string \| RichStr` | — | Description below the title |
| `bottomChildren` | `ReactNode` | — | Content below a divider, under the main content |
| `rightChildren` | `ReactNode` | — | Content on the right side. Mutually exclusive with `onClose`. |
| `onClose` | `() => void` | — | Close button callback. When omitted, no close button is rendered. |

## Usage

```tsx
import { MessageCard } from "@opal/components";

// Simple info message
<MessageCard
  variant="info"
  title="Heads up"
  description="Changes apply to newly indexed documents only."
/>

// Warning with bottom content
<MessageCard
  variant="warning"
  title="Re-indexing required"
  description="Toggle this setting to re-index all documents."
  bottomChildren={<Button>Re-index Now</Button>}
/>

// Error state
<MessageCard
  variant="error"
  title="Connection failed"
  description="Unable to reach the embedding model server."
/>
```
