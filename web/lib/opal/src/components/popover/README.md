# Popover

**Import:** `import { Popover, PopoverMenu } from "@opal/components";`

A floating panel anchored to a trigger element. Built on Radix Popover primitives. Supports
both uncontrolled (open on click) and controlled (`open` + `onOpenChange`) modes.

`Popover` is a compound component: `Popover.Trigger`, `Popover.Anchor`, `Popover.Content`,
`Popover.Close`, and `Popover.Menu`.

## Props

### `Popover` (root)

Forwarded to `@radix-ui/react-popover` `Root`. Most common:

| Prop           | Type                      | Default | Description                            |
| -------------- | ------------------------- | ------- | -------------------------------------- |
| `open`         | `boolean`                 | —       | Controlled open state                  |
| `onOpenChange` | `(open: boolean) => void` | —       | Open-state callback                    |
| `modal`        | `boolean`                 | `false` | Whether interaction outside is blocked |

### `Popover.Content`

| Prop         | Type                                                          | Default    | Description                                     |
| ------------ | ------------------------------------------------------------- | ---------- | ----------------------------------------------- |
| `width`      | `"fit" \| "sm" \| "md" \| "lg" \| "xl" \| "2xl" \| "trigger"` | `"fit"`    | Popover width preset                            |
| `container`  | `HTMLElement \| null`                                         | —          | Portal container (use to render inside a modal) |
| `align`      | `"start" \| "center" \| "end"`                                | `"center"` | Alignment along the side axis                   |
| `sideOffset` | `number`                                                      | `4`        | Distance in pixels between trigger and popover  |

### `Popover.Menu`

| Prop                 | Type                        | Default | Description                                                                                                       |
| -------------------- | --------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `children`           | `ReactNode[]`               | —       | Menu items. `null` renders a separator; `undefined`/`false` is filtered. Leading/trailing separators are removed. |
| `footer`             | `ReactNode`                 | —       | Footer area below the scroll region, separated by a divider                                                       |
| `scrollContainerRef` | `RefObject<HTMLDivElement>` | —       | Ref for programmatic scrolling                                                                                    |

## Usage

```tsx
import { Popover } from "@opal/components";

// Basic
<Popover>
  <Popover.Trigger asChild>
    <Button>Options</Button>
  </Popover.Trigger>
  <Popover.Content align="end">
    <div>Content here</div>
  </Popover.Content>
</Popover>

// With menu, separators, and footer
<Popover>
  <Popover.Trigger asChild>
    <Button>Menu</Button>
  </Popover.Trigger>
  <Popover.Content width="lg">
    <Popover.Menu footer={<Button>Apply</Button>}>
      <LineItemButton title="Option 1" />
      <LineItemButton title="Option 2" />
      {null}
      <LineItemButton title="Option 3" />
    </Popover.Menu>
  </Popover.Content>
</Popover>

// Controlled
const [open, setOpen] = useState(false);
<Popover open={open} onOpenChange={setOpen}>
  <Popover.Trigger asChild>
    <Button>Click me</Button>
  </Popover.Trigger>
  <Popover.Content>...</Popover.Content>
</Popover>
```
