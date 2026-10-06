# AttachmentItem

**Import:** `import { AttachmentItem, type AttachmentItemProps } from "@opal/layouts";`

A static row for a file-like resource: a tinted tile (icon or image) beside a
title and description, an expanding center slot, and a reserved trailing
slot. It has the same layout as
[`AttachmentItemButton`](../../components/buttons/attachment-item-button/README.md),
with no interactivity: no hover, focus, click, selected state or tooltip.
Both render the same internal row, `AttachmentItemBody`, so their layout
cannot drift apart.

Use it for a row that only shows something, such as a group on an access list.
Put controls (a remove button, a role picker) in `rightChildren`. When the
whole row must react to a click, use `AttachmentItemButton`.

## Structure

```
root          div, rounded --radius-12, surface from prominence
├─ title      tile + Content (main-ui / section)
│   ├─ tile   icon on tint, or image cover-filling
│   └─ Content
├─ center     centerChildren, flex-1
└─ action     rightChildren, min-width --spacing-block-36, always reserved
```

## Props

| Prop                  | Type                                    | Default      | Description                                     |
| --------------------- | --------------------------------------- | ------------ | ----------------------------------------------- |
| `icon`                | `IconFunctionComponent`                 | —            | Icon on the tile. Exclusive with `imageSrc`.    |
| `imageSrc`            | `string`                                | —            | Image filling the tile. Needs `imageAlt`.       |
| `imageAlt`            | `string`                                | —            | Alt text for `imageSrc`.                        |
| `title`               | `string \| RichStr`                     | **required** | Main label                                      |
| `titleMaxLines`       | `number`                                | `1`          | Truncate the title after N lines                |
| `description`         | `string \| RichStr`                     | —            | Secondary line                                  |
| `descriptionMaxLines` | `number`                                | `1`          | Truncate the description after N lines          |
| `prominence`          | `"primary" \| "secondary" \| "tertiary"` | `"tertiary"` | Surface: `tint-00`, `tint-01`, or transparent   |
| `centerChildren`      | `ReactNode`                             | —            | Between the title and the trailing slot         |
| `rightChildren`       | `ReactNode`                             | —            | Trailing slot                                   |

Other `div` attributes (`aria-*`, `data-*`, handlers) pass to the root.

## Usage

```tsx
<AttachmentItem
  prominence="secondary"
  icon={SvgUsers}
  title={group.name}
  description={t("memberCount", { count: group.users.length })}
  rightChildren={
    <Button icon={SvgX} size="sm" prominence="internal" onClick={remove} />
  }
/>
```
