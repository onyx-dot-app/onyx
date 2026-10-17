# Collapsible

**Import:** `import { Collapsible, type CollapsibleProps } from "@opal/components";`

A section whose header opens and closes the body under it. The header is a title, description and optional tag (an Opal `ContentAction` at the `main-content` size (`main-content-emphasis` title), not overridable) with a Fold/View All `Button` on the right; `children` is the body. The body is a `Collapsible.Content` with `paddingTop={3}` (0.75rem) under the header, inside the part that animates, so it closes with the body. The section is a preset of the composable parts below: one state, one toggle, one spacing mechanism. The body animates its height, and while closed it is `inert`, so its fields cannot take focus. No Radix.

## Usage

```tsx
<Collapsible
  title="Schedule"
  description="Specify how the connector will operate indexing."
>
  <InputVertical title="Refresh frequency">…</InputVertical>
</Collapsible>;

// Controlled
const [open, setOpen] = useState(false);
<Collapsible title="Schedule" open={open} onOpenChange={setOpen}>
  …
</Collapsible>;
```

## Props

| Prop            | Type                      | Default | Description                                                  |
| --------------- | ------------------------- | ------- | ------------------------------------------------------------ |
| `title`         | `string \| RichStr`       | —       | Section title, in the header                                 |
| `description`   | `string \| RichStr`       | —       | Line under the title, in the header                          |
| `tag`           | `TagProps`                | —       | Tag next to the title                                        |
| `open`          | `boolean`                 | —       | Controlled open state. Pair with `onOpenChange`              |
| `onOpenChange`  | `(open: boolean) => void` | —       | Called with the next state when the header is clicked        |
| `defaultOpen`   | `boolean`                 | `true`  | Initial open state when uncontrolled                         |
| `disabled`      | `boolean`                 | `false` | Locks the current open state; clicks and keys do nothing     |
| `rightChildren` | `ReactNode`               | —       | Controls before the fold button. Clicks inside do not toggle |
| `children`      | `ReactNode`               | —       | The body that opens and closes                               |

The whole header row toggles on click and drives the `Button`'s hover state. The `Button` is the keyboard control: Tab reaches it, keyboard focus shows as its hover state (no focus ring), and Enter or Space toggles. It carries `aria-expanded` and `aria-controls` pointing at the body. Its tooltip comes from `OpalStrings`: "Fold" while open (`collapsibleFold`), "View All" while folded (`collapsibleExpand`), and its accessible name includes the title (`collapsibleFoldSection`, `collapsibleExpandSection`), e.g. "Expand Schedule". The body renders from the first open and then stays mounted, so a section that starts closed does no work (fetches included) until it is opened. Reduced motion turns the animation off.

## Composable parts

For a collapsible whose header you draw yourself (a card, a row, a custom button), use the parts instead of the section:

```tsx
<Collapsible.Root open={open} onOpenChange={setOpen}>
  <Collapsible.Trigger asChild>
    <button>…your header…</button>
  </Collapsible.Trigger>
  <Collapsible.Content>…body…</Collapsible.Content>
</Collapsible.Root>
```

| Part                  | Props                                                       | Notes                                                                                                                                                                                     |
| --------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Collapsible.Root`    | `open`, `onOpenChange`, `defaultOpen` (`false`), `disabled` | Holds the state; renders a `div` with `data-state`.                                                                                                                                       |
| `Collapsible.Trigger` | `asChild`, plus `<button>` props                            | Toggles the root. Sets `aria-expanded`, `aria-controls` and `data-state` on its element.                                                                                                  |
| `Collapsible.Content` | `paddingTop` (`0`), `keepMounted`                           | Opens and closes with `Fold`'s animation; drops its children once closed unless `keepMounted`. `paddingTop` (a spacing step) sits inside the animation, so it takes no room while closed. |
