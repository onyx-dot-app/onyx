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
</Tabs>;
```

## Variants

### Contained (default)

Equal-width tabs, 36px tall, laid out in a grid on a tinted background. The active tab sits on a white card with a subtle shadow, which slides to the next tab when the selection changes. Best for primary page-level navigation.

```tsx
<Tabs variant="contained">
  <Tabs.List>
    <Tabs.Trigger value="a">Tab A</Tabs.Trigger>
    <Tabs.Trigger value="b">Tab B</Tabs.Trigger>
  </Tabs.List>
</Tabs>
```

### Pill

Content-width tabs. The active tab's filled background and the underline indicator both slide between tabs. Good for secondary navigation or filter-style tabs.

```tsx
<Tabs variant="pill">
  <Tabs.List>
    <Tabs.Trigger value="all">All</Tabs.Trigger>
    <Tabs.Trigger value="active">Active</Tabs.Trigger>
  </Tabs.List>
</Tabs>
```

### Underline

Like pill but without the filled active background — only the underline indicator is shown, and it slides between tabs.

```tsx
<Tabs variant="underline">
  <Tabs.List>
    <Tabs.Trigger value="cloud">Cloud-based</Tabs.Trigger>
    <Tabs.Trigger value="self">Self-hosted</Tabs.Trigger>
  </Tabs.List>
</Tabs>
```

### Animation

Every variant has one active-state element (contained card, pill background, underline bar) that slides from the old tab to the new one. It moves with a `transform`, holds still on its first placement and while the tabs scroll, and turns off for reduced motion. Panels (`Tabs.Content`) swap without animation.

A string label renders as an Opal `Content` with `color="interactive"`: each tab is an interactive surface whose state sets `--interactive-foreground` and `--interactive-foreground-icon`, so title and icon colours fade with the slide. Contained labels use the `main-ui` size (16px icon); pill and underline use `secondary` (12px icon).

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
<Tabs variant="pill">
  <Tabs.List rightChildren={<Button size="sm">Add New</Button>}>
    <Tabs.Trigger value="all">All</Tabs.Trigger>
    <Tabs.Trigger value="mine">Mine</Tabs.Trigger>
  </Tabs.List>
</Tabs>
```

### Horizontal scroll arrows

When tabs overflow the available width, show navigation arrows:

```tsx
<Tabs variant="pill">
  <Tabs.List enableScrollArrows>
    {manyTabs.map((t) => (
      <Tabs.Trigger key={t.value} value={t.value}>
        {t.label}
      </Tabs.Trigger>
    ))}
  </Tabs.List>
</Tabs>
```

### Controlled mode

```tsx
<Tabs value={activeTab} onValueChange={setActiveTab}>
  …
</Tabs>
```

### Content padding

```tsx
<Tabs.Content value="tab" padding={2}>
  Padded content
</Tabs.Content>
```

## Props

### `Tabs` (Root)

Forwards all [Radix Tabs.Root](https://www.radix-ui.com/docs/primitives/components/tabs) props except `className` / `style`.

| Prop            | Type                                   | Default       | Description                            |
| --------------- | -------------------------------------- | ------------- | -------------------------------------- |
| `variant`       | `"contained" \| "pill" \| "underline"` | `"contained"` | Visual variant for the whole tab group |
| `defaultValue`  | `string`                               | —             | Initially active tab (uncontrolled)    |
| `value`         | `string`                               | —             | Controlled active tab                  |
| `onValueChange` | `(value: string) => void`              | —             | Called when active tab changes         |

### `Tabs.List`

| Prop                 | Type        | Default | Description                                          |
| -------------------- | ----------- | ------- | ---------------------------------------------------- |
| `rightChildren`      | `ReactNode` | —       | Content pinned to the right (pill/underline only)    |
| `enableScrollArrows` | `boolean`   | `false` | Show scroll arrows on overflow (pill/underline only) |

### `Tabs.Trigger`

| Prop          | Type                                     | Default      | Description                            |
| ------------- | ---------------------------------------- | ------------ | -------------------------------------- |
| `value`       | `string`                                 | **required** | Tab value                              |
| `icon`        | `FunctionComponent<IconProps>`           | —            | Icon before the label                  |
| `tooltip`     | `string`                                 | —            | Tooltip on hover                       |
| `tooltipSide` | `"top" \| "bottom" \| "left" \| "right"` | `"top"`      | Tooltip placement                      |
| `disabled`    | `boolean`                                | —            | Disables the tab (tooltip still shows) |
| `isLoading`   | `boolean`                                | —            | Shows a spinner after the label        |

### `Tabs.Content`

| Prop          | Type      | Default      | Description                                                                            |
| ------------- | --------- | ------------ | -------------------------------------------------------------------------------------- |
| `value`       | `string`  | **required** | Must match a `Tabs.Trigger` value                                                      |
| `padding`     | `Spacing` | `0`          | Additional inner padding, as a spacing step (`N / 4` rem)                              |
| `keepMounted` | `boolean` | `false`      | Keeps the panel mounted but hidden while inactive, so form state survives a tab switch |
