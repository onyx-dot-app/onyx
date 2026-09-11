# AttachmentItemButton

**Import:** `import { AttachmentItemButton, type AttachmentItemButtonProps } from "@opal/components";`

A row for a file-like resource: a large tinted tile (icon or image) beside a
title/description, an expanding center slot, and a reserved trailing action
slot. The tile's rounding (`--radius-08`) complements the row's container
rounding (`--radius-12`).

## Structure

```
root                      Interactive.Stateful + Interactive.Container
├─ title                  tile + icon-less Content (main-ui / section, frozen)
│   ├─ tile               icon on tint, or image cover-filling; Checkbox when selected
│   └─ Content            title, description, optional inline editing
├─ center                 centerChildren — flex-1, caller-aligned
└─ action                 rightChildren — min-width --spacing-block-36, always reserved
```

## Tile

Exactly one of two arms, enforced at the type level:

- `icon` — centered on the tinted tile.
- `imageSrc` + `imageAlt` — image fills the tile (`object-fit: cover`).
  `imageAlt` is mandatory: the image is content, not chrome.

When `state="selected"`, the tile swaps its content for a checked `Checkbox`.

## Interactivity

Three modes, same contract as `LineItemButton`:

- **Button** (default) — focusable `role="button"` div with native-style
  Enter/Space activation. Not a `<button>`, so action buttons in
  `rightChildren` never nest invalid HTML. Clicks and keystrokes from nested
  interactive children never activate the row — no `stopPropagation` needed
  at call sites.
- **Anchor** — pass `href` (+ `target`).
- **Presentational** — pass `presentational`; the row renders no control
  semantics of its own and defers them to the primitive that owns it.

`prominence` sets the intensity at rest: `"primary"` rests on
`background-tint-00`, `"secondary"` on `background-tint-01`, and
`"tertiary"` (default) is transparent. Hover / selected / disabled palettes
come from `Interactive.Stateful` and are shared across all three.

## Content

The `Content` axis is frozen at `main-ui`/`section` — the tile is this
component's identity, so `sizePreset`/`variant` are not exposed. `title` and
`description` default to one line each (`titleMaxLines` /
`descriptionMaxLines` widen this). `editable` + `onTitleChange` enable
Content's inline title editing.

## Usage

```tsx
// File row: click-selectable, hover-revealed delete
<AttachmentItemButton
  icon={SvgFileText}
  title={file.name}
  description="PDF"
  state={selected ? "selected" : "empty"}
  onClick={toggle}
  centerChildren={<Text font="secondary-body" color="text-03">2 days ago</Text>}
  rightChildren={<Button icon={SvgTrash} onClick={remove} prominence="tertiary" size="sm" />}
/>

// Static token row on a page surface
<AttachmentItemButton
  presentational
  prominence="secondary"
  icon={SvgKey}
  title={token.name}
  description={token.display}
  rightChildren={<Button icon={SvgTrash} onClick={revoke} prominence="tertiary" size="sm" />}
/>
```
