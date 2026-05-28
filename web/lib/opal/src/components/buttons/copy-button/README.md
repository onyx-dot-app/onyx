# CopyButton

A button that copies text to the clipboard on click. The icon transitions through three states: idle (`SvgCopy`), copied (`SvgCheck`), and error (`SvgAlertTriangle`). The icon is not overridable by callers.

## Usage

### Icon-only (omit `children`)

```tsx
import { CopyButton } from "@opal/components";

<CopyButton getCopyText={() => apiKey} tooltip="Copy API key" />
```

### With label (provide `children`)

```tsx
<CopyButton getCopyText={() => shareUrl}>
  Copy link
</CopyButton>
```

### Rich copy (HTML + plain text)

```tsx
<CopyButton
  getCopyText={() => "plain text fallback"}
  getHtmlContent={() => "<b>rich</b> content"}
/>
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `getCopyText` | `() => string` | — | **Required.** Returns the text written to the clipboard. |
| `getHtmlContent` | `() => string` | `undefined` | Optional HTML content for rich copy. Falls back to `getCopyText` when the Clipboard API is unavailable. |
| `children` | `string` | `undefined` | Optional label. When provided the button renders with text; when omitted it is icon-only. |
| `tooltip` | `string` | `"Copy"` | Tooltip text shown in the idle state. Overridden by `"Copied!"` / `"Failed to copy"` on state change. |
| `prominence` | `ButtonProminence` | `"tertiary"` | Visual prominence level. |
| `size` | `ContainerSizeVariants` | `"lg"` | Size preset. |

All other `Button` props (except `icon`, `onClick`, `rightIcon`) are forwarded.

## Notes

- Uses `navigator.clipboard` when available, falls back to `copy-to-clipboard` package.
- The icon is always controlled by internal copy state — it cannot be overridden via props.
- The copied / error state resets after 3 seconds.
