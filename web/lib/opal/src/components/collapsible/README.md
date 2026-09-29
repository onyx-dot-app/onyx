# Collapsible

**Import:** `import { Collapsible } from "@opal/components";`

A titled section that folds its content away. The header carries a title, an optional description, an optional `rightChildren` slot, and the collapse button.

## Usage

```tsx
import { Collapsible, Button } from "@opal/components";

<Collapsible
  title="Authentication Account"
  description="Use a shared service account."
  rightChildren={<Button prominence="tertiary">2 Saved Accounts</Button>}
  defaultOpen
>
  <Card border="solid" rounding={4}>…</Card>
</Collapsible>

// Controlled
<Collapsible title="Details" open={open} onOpenChange={setOpen}>
  …
</Collapsible>
```

## Props

| Prop            | Type                      | Default | Description                                                                                              |
| --------------- | ------------------------- | ------- | -------------------------------------------------------------------------------------------------------- |
| `title`         | `string \| RichStr`       | —       | Header title                                                                                             |
| `description`   | `string \| RichStr`       | —       | Header description, under the title                                                                      |
| `rightChildren` | `ReactNode`               | —       | Rendered in the header, left of the collapse button; keeps its own clicks                                |
| `open`          | `boolean`                 | —       | Controlled open state                                                                                    |
| `defaultOpen`   | `boolean`                 | `false` | Uncontrolled initial open state                                                                          |
| `onOpenChange`  | `(open: boolean) => void` | —       | Called with the next state when the fold toggles                                                         |
| `children`      | `ReactNode`               | —       | The folded content; stays mounted while closed, inert and hidden from assistive tech, so the fold animates both ways |
| `ref`           | `Ref<HTMLDivElement>`     | —       | Ref forwarded to the root `<div>`                                                                        |

## Behaviour

- **One control.** The header's `Content` is wrapped in a `<label>` for the collapse button, so a click on the title or description toggles the fold through the button itself: one focus stop, one aria-label, no nested interactive elements. `rightChildren` sits outside the label.
- **The fold animates both ways.** Grid rows move between `0fr` and `1fr` with a fade on a 200ms clock, the same fold the foldable `Divider` uses. The content is never unmounted. Reduced motion turns the transition off.
- **Strings.** The button's aria-label comes from the Opal strings contract (`collapsibleExpand`, `collapsibleCollapse`), so the app supplies the translations.
