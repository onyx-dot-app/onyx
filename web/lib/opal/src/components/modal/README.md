# Modal

**Import:** `import { Modal, BasicModalFooter } from "@opal/components";`

Radix Dialog compound, the Figma Modal. `Modal` is the Radix root (`open`, `onOpenChange`). `Modal.Content` renders the scrim, positioning, and the card. `Modal.Header`, `Modal.Body`, and `Modal.Footer` are the card's sections.

```tsx
<Modal open={open} onOpenChange={setOpen}>
  <Modal.Content width="md">
    <Modal.Header
      icon={SvgSettings}
      title="Modal title"
      description="Supporting description."
      onClose={() => setOpen(false)}
    />
    <Modal.Body>Content</Modal.Body>
    <Modal.Footer>
      <BasicModalFooter
        cancel={<Button prominence="secondary">Cancel</Button>}
        submit={<Button>Confirm</Button>}
      />
    </Modal.Footer>
  </Modal.Content>
</Modal>
```

## Modal.Content

| Prop | Type | Default | Description |
|---|---|---|---|
| `width` | `"full" \| "xl" \| "lg" \| "md" \| "sm"` | `"xl"` | Card width (`80dvw`, 60rem, 50rem, 40rem, 30rem) |
| `height` | `"fit" \| "sm" \| "lg" \| "full"` | `"fit"` | Card height and scroll behavior |
| `position` | `"center" \| "top"` | `"center"` | `"top"` pins near the viewport top (command-menu position) |
| `preventAccidentalClose` | `boolean` | `true` | After the user types in any text input, the first Escape/outside-click focuses the close button and the second closes |
| `skipOverlay` | `boolean` | `false` | Omit the scrim |
| `background` | `"default" \| "gray"` | `"default"` | Card background (`tint-00` or `tint-01`) |
| `bottomSlot` | `ReactNode` | — | Rendered below the card, inside the dialog's focus scope |

## Modal.Header

| Prop | Type | Description |
|---|---|---|
| `icon`, `moreIcon1`, `moreIcon2` | `IconFunctionComponent` | Heading icons. Omitting `icon` gives the minimal (icon-less) variant |
| `title` | `string \| RichStr` | Required |
| `description` | `string \| RichStr` | Optional, also wired to `aria-describedby` |
| `onClose` | `() => void` | Renders the close button |

`children` render below the title stack (e.g. a search input).

## Modal.Body

`twoTone` (default `true`) gives the body the gray `tint-01` background separating it from header and footer. Scrolls when the card height caps.

## Modal.Footer

Right-aligned action row. `BasicModalFooter` adds the common layout: optional `left` slot plus right-aligned `cancel`/`submit`.

## Positioning

When a `[data-main-container]` element is present (the content area beside the sidebar), the modal centers on it instead of the viewport, and falls back to viewport centering on medium screens or when the container is absent.

## Deferred

The remaining Figma header/footer content variants (Search, Card, Panel, Checkbox, Message) are follow-ups.
