# Collapsible

**Import:** `import { Collapsible, type CollapsibleProps } from "@opal/components";`

A section whose header opens and closes the body under it. The header is a title, description and optional tag (an Opal `ContentAction` at the `main-content` size (`main-content-emphasis` title), not overridable) with a Fold/Expand `Button` on the right; `children` is the body. The body has a 0.75rem top padding (`pt-3`) under the header, inside the part that animates, so it closes with the body. The body animates its height, and while closed it is `inert`, so its fields cannot take focus. No Radix.

## Usage

```tsx
<Collapsible
  title="Schedule"
  description="Specify how the connector will operate indexing."
>
  <InputVertical title="Refresh frequency">…</InputVertical>
</Collapsible>

// Controlled
const [open, setOpen] = useState(false);
<Collapsible title="Schedule" open={open} onOpenChange={setOpen}>
  …
</Collapsible>
```

## Props

| Prop           | Type                      | Default | Description                                              |
| -------------- | ------------------------- | ------- | -------------------------------------------------------- |
| `title`        | `string \| RichStr`       | —       | Section title, in the header                             |
| `description`  | `string \| RichStr`       | —       | Line under the title, in the header                      |
| `tag`          | `TagProps`                | —       | Tag next to the title                                    |
| `open`         | `boolean`                 | —       | Controlled open state. Pair with `onOpenChange`          |
| `onOpenChange` | `(open: boolean) => void` | —       | Called with the next state when the header is clicked    |
| `defaultOpen`  | `boolean`                 | `true`  | Initial open state when uncontrolled                     |
| `disabled`     | `boolean`                 | `false` | Locks the current open state; clicks and keys do nothing |
| `children`     | `ReactNode`               | —       | The body that opens and closes                           |

The whole header row toggles on click and drives the `Button`'s hover state. The `Button` is the keyboard control: Tab reaches it, keyboard focus shows as its hover state (no focus ring), and Enter or Space toggles. It carries `aria-expanded` and `aria-controls` pointing at the body. Its tooltip comes from `OpalStrings` (`collapsibleFold`, `collapsibleExpand`), and its accessible name includes the title (`collapsibleFoldSection`, `collapsibleExpandSection`), e.g. "Expand Schedule". The body renders from the first open and then stays mounted, so a section that starts closed does no work (fetches included) until it is opened. Reduced motion turns the animation off.
