# InputSelect

**Import:** `import { InputSelect } from "@opal/components";`

Styled dropdown on Radix Select, the Figma `Input/Select`. Compound component: the root owns value state (controlled or uncontrolled), `Trigger` renders the `.opal-input` chrome with the selected item's icon and label (truncating with a tooltip when clipped), `Content` is the popper matching the trigger width, `Item`s render as `ContentAction` rows with Radix driving highlight and selection.

For filterable lists, render `Search` as the first child of `Content`. It is a sticky query row: the consumer owns the query state and renders only the matching `Item`s. The row keeps printable keys in its input (Radix typeahead never fires), focuses itself when the menu opens, hands focus to the option list on ArrowDown (Radix then drives highlight and Enter), and lets Escape close the menu. Clear the query in `onOpenChange` so each open starts unfiltered.

```tsx
<InputSelect.Content>
  <InputSelect.Search
    value={query}
    onChange={(e) => setQuery(e.target.value)}
    placeholder="Search agents..."
  />
  {filtered.map((a) => (
    <InputSelect.Item key={a.id} value={String(a.id)}>
      {a.name}
    </InputSelect.Item>
  ))}
</InputSelect.Content>
```

```tsx
<InputSelect value={value} onValueChange={setValue} error={touched && !value}>
  <InputSelect.Trigger placeholder="Choose a model" />
  <InputSelect.Content>
    <InputSelect.Group>
      <InputSelect.Label>OpenAI</InputSelect.Label>
      <InputSelect.Item value="gpt" icon={SvgCpu} description="Default">
        GPT-5
      </InputSelect.Item>
    </InputSelect.Group>
    <InputSelect.Separator />
    <InputSelect.Item value="opus">Claude Opus</InputSelect.Item>
  </InputSelect.Content>
</InputSelect>
```

## Parts

| Part | Key props | Notes |
|---|---|---|
| `InputSelect` | Radix Root props + `error`, `disabled` | `error`/`disabled` drive the trigger chrome variant |
| `.Trigger` | `placeholder`, `rightSection` | Custom `children` replace the selected-item display |
| `.Content` | Radix Content props | Popper, trigger-width, 18rem max height with scroll |
| `.Item` | `value`, `children`, `icon`, `description`, `wrapDescription` | The selected item's icon and label mirror into the trigger |
| `.Group` / `.Label` | Radix props | Uppercase group label |
| `.Separator` | `paddingParallel`, `paddingPerpendicular` | Opal `Divider` |

Requires the `@radix-ui/react-select` peer dependency. The selected row uses the `select-heavy` selected tokens (`action-link-01` background with the interactive foreground vars), and keyboard/hover highlight comes from Radix's `data-highlighted`.
