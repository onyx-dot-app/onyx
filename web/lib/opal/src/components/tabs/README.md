# Tabs

Compound tab navigation component built on Radix UI Tabs. Three visual variants, animated pill indicator, optional scroll arrows, and right-side slot.

## Usage

```tsx
import { Tabs } from "@opal/components";

<Tabs defaultValue="overview">
  <Tabs.List>
    <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
    <Tabs.Trigger value="details">Details</Tabs.Trigger>
  </Tabs.List>
  <Tabs.Content value="overview">Overview content</Tabs.Content>
  <Tabs.Content value="details">Details content</Tabs.Content>
</Tabs>
```

## Variants

### Contained (default)
Equal-width tabs laid out in a grid on a tinted background. Active tab gets a white card with a subtle shadow. Best for primary page-level navigation.

```tsx
<Tabs.List variant="contained">
  <Tabs.Trigger value="a">Tab A</Tabs.Trigger>
  <Tabs.Trigger value="b">Tab B</Tabs.Trigger>
</Tabs.List>
```

### Pill
Content-width tabs with a sliding underline indicator that animates between active tabs. Good for secondary navigation or filter-style tabs.

```tsx
<Tabs.List variant="pill">
  <Tabs.Trigger value="all">All</Tabs.Trigger>
  <Tabs.Trigger value="active">Active</Tabs.Trigger>
</Tabs.List>
```

### Underline
Like pill but without the filled active background on the trigger — only the underline indicator is shown.

```tsx
<Tabs.List variant="underline">
  <Tabs.Trigger value="cloud">Cloud-based</Tabs.Trigger>
  <Tabs.Trigger value="self">Self-hosted</Tabs.Trigger>
</Tabs.List>
```

## Features

### Icons and Tooltips

```tsx
<Tabs.Trigger value="settings" icon={SvgSettings} tooltip="Manage settings">
  Settings
</Tabs.Trigger>
```

### Disabled trigger with tooltip

```tsx
<Tabs.Trigger value="premium" disabled tooltip="Upgrade to unlock">
  Premium
</Tabs.Trigger>
```

### Right-side content

```tsx
<Tabs.List variant="pill" rightContent={<Button size="sm">Add New</Button>}>
  <Tabs.Trigger value="all">All</Tabs.Trigger>
  <Tabs.Trigger value="mine">Mine</Tabs.Trigger>
</Tabs.List>
```

### Horizontal scroll arrows

When tabs overflow the available width, show navigation arrows:

```tsx
<Tabs.List variant="pill" enableScrollArrows>
  {manyTabs.map((t) => (
    <Tabs.Trigger key={t.value} value={t.value}>{t.label}</Tabs.Trigger>
  ))}
</Tabs.List>
```

### Controlled mode

```tsx
<Tabs value={activeTab} onValueChange={setActiveTab}>
  …
</Tabs>
```

### Content padding

```tsx
<Tabs.Content value="tab" padding={0.5}>
  Padded content
</Tabs.Content>
```

## Props

### `Tabs` (Root)

Forwards all [Radix Tabs.Root](https://www.radix-ui.com/docs/primitives/components/tabs) props except `className` / `style`.

| Prop | Type | Default | Description |
|---|---|---|---|
| `defaultValue` | `string` | — | Initially active tab (uncontrolled) |
| `value` | `string` | — | Controlled active tab |
| `onValueChange` | `(value: string) => void` | — | Called when active tab changes |

### `Tabs.List`

| Prop | Type | Default | Description |
|---|---|---|---|
| `variant` | `"contained" \| "pill" \| "underline"` | `"contained"` | Visual variant |
| `rightContent` | `ReactNode` | — | Content pinned to the right (pill/underline only) |
| `enableScrollArrows` | `boolean` | `false` | Show scroll arrows on overflow (pill/underline only) |
| `className` | `string` | — | Additional class names |

### `Tabs.Trigger`

| Prop | Type | Default | Description |
|---|---|---|---|
| `value` | `string` | **required** | Tab value |
| `icon` | `FunctionComponent<IconProps>` | — | Icon before the label |
| `tooltip` | `string` | — | Tooltip on hover |
| `tooltipSide` | `"top" \| "bottom" \| "left" \| "right"` | `"top"` | Tooltip placement |
| `disabled` | `boolean` | — | Disables the tab (tooltip still shows) |
| `isLoading` | `boolean` | — | Shows a spinner after the label |
| `variant` | `"contained" \| "pill" \| "underline"` | inherited | Override the list variant |

### `Tabs.Content`

| Prop | Type | Default | Description |
|---|---|---|---|
| `value` | `string` | **required** | Must match a `Tabs.Trigger` value |
| `padding` | `number` | `0` | Inner padding in rem units |
| `className` | `string` | — | Additional class names |
