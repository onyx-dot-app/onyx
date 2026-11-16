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

| Prop                     | Type                                     | Default     | Description                                                                                                           |
| ------------------------ | ---------------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------- |
| `width`                  | `"full" \| "xl" \| "lg" \| "md" \| "sm"` | `"xl"`      | Card width (`80dvw`, 60rem, 50rem, 40rem, 30rem)                                                                      |
| `height`                 | `"fit" \| "sm" \| "lg" \| "full"`        | `"fit"`     | Card height and scroll behavior                                                                                       |
| `preventAccidentalClose` | `boolean`                                | `true`      | After the user types in any text input, the first Escape/outside-click focuses the close button and the second closes |
| `skipOverlay`            | `boolean`                                | `false`     | Omit the scrim                                                                                                        |
| `background`             | `"default" \| "gray"`                    | `"default"` | Card background (`tint-00` or `tint-01`)                                                                              |
| `bottomSlot`             | `ReactNode`                              | —           | Rendered below the card, inside the dialog's focus scope                                                              |

## Modal.Backdrop

For flows that replace `Modal.Content` between screens, mount one `Modal.Backdrop`
directly inside `Modal`. Set `skipOverlay` on each content screen. The backdrop
stays mounted during navigation, so its entrance animation runs only when the
flow opens. Single-screen modals can keep the default `Modal.Content` overlay.

## Modal.Header

| Prop                             | Type                           | Description                                                                                                                          |
| -------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `icon`, `moreIcon1`, `moreIcon2` | `IconFunctionComponent`        | Heading icons. Omitting `icon` gives the minimal (icon-less) variant                                                                 |
| `color`                          | `StatusColor \| "interactive"` | Colour mode of the icon and title, as on `Content` (a status colours the title and icon)                                             |
| `title`                          | `string \| RichStr`            | Required                                                                                                                             |
| `description`                    | `string \| RichStr`            | Optional, also wired to `aria-describedby`                                                                                           |
| `onClose`                        | `() => void`                   | Renders the close button, with a "Close" tooltip on its start side on pointer hover (not on focus, so Escape still closes the modal) |

`children` render below the title stack (e.g. a search input).

Use `maxHeight` to cap a content-sized modal, for example `height="fit" maxHeight="80dvh"`. The viewport limit still applies.

## Modal.Body

`twoTone` (default `true`) gives the body the gray `tint-01` background separating it from header and footer. Scrolls when the card height caps, through a [`ShadowDiv`](../shadow-div/README.md): a shadow at the top once scrolled, and a mask fading the content at the bottom while more is below. Reserves equal scrollbar space on both sides to keep content centered and prevent shifts when scrolling becomes necessary.

## Modal.Footer

Right-aligned action row. `BasicModalFooter` adds the common layout: optional `left` slot plus right-aligned `cancel`/`submit`.

Use `stackOnSmallScreens` inside `<Modal.Footer wrap>` to place navigation above
the action buttons on narrow screens. The default layout stays unchanged.

## Positioning

Every modal is top-aligned, with no prop to change it. The card's top edge sits at `max(2rem, 12dvh)`, so a height change grows or shrinks the card downward instead of moving it. The height limit keeps the same gap at the bottom, so the bottom gap is never less than the top one. In the desktop app the top offset also includes the title bar height (`--onyx-titlebar-height`); the gap below the title bar and the bottom gap stay equal.

When a `[data-main-container]` element is present (the content area beside the sidebar), the modal centers horizontally on it instead of the viewport, and falls back to viewport centering on medium screens or when the container is absent.

## Deferred

The remaining Figma header/footer content variants (Search, Card, Panel, InputCheckbox, Message) are follow-ups.
