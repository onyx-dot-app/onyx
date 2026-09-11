# InputSingleSelect

**Import:** `import { InputSingleSelect } from "@opal/components";`

Styled dropdown on Radix Select, the Figma `Input/Select`. Compound component: the root owns value state (controlled or uncontrolled), `Trigger` renders the `.opal-input` chrome with the selected item's icon and label (truncating with a tooltip when clipped), `Content` is the popper matching the trigger width, `Item`s render as `ContentAction` rows with Radix driving highlight and selection.

For filterable lists, render `Search` as the first child of `Content`. It is a sticky query row: the consumer owns the query state and renders only the matching `Item`s. The row keeps printable keys in its input (Radix typeahead never fires), focuses itself when the menu opens, hands focus to the option list on ArrowDown (Radix then drives highlight and Enter), and lets Escape close the menu. Clear the query in `onOpenChange` so each open starts unfiltered.

```tsx
<InputSingleSelect.Content>
  <InputSingleSelect.Search
    value={query}
    onChange={(e) => setQuery(e.target.value)}
    placeholder="Search agents..."
  />
  {filtered.map((a) => (
    <InputSingleSelect.Item key={a.id} value={String(a.id)}>
      {a.name}
    </InputSingleSelect.Item>
  ))}
</InputSingleSelect.Content>
```

```tsx
<InputSingleSelect value={value} onValueChange={setValue} error={touched && !value}>
  <InputSingleSelect.Trigger placeholder="Choose a model" />
  <InputSingleSelect.Content>
    <InputSingleSelect.Group>
      <InputSingleSelect.Label>OpenAI</InputSingleSelect.Label>
      <InputSingleSelect.Item value="gpt" icon={SvgCpu} description="Default">
        GPT-5
      </InputSingleSelect.Item>
    </InputSingleSelect.Group>
    <InputSingleSelect.Separator />
    <InputSingleSelect.Item value="opus">Claude Opus</InputSingleSelect.Item>
  </InputSingleSelect.Content>
</InputSingleSelect>
```

## Parts

| Part                | Key props                                                     | Notes                                                      |
| ------------------- | ------------------------------------------------------------- | ---------------------------------------------------------- |
| `InputSingleSelect`       | Radix Root props + `error`, `disabled`                        | `error`/`disabled` drive the trigger chrome variant        |
| `.Trigger`          | `placeholder`, `rightSection`                                 | Custom `children` replace the selected-item display        |
| `.Content`          | Radix Content props                                           | Popper, trigger-width, 18rem max height with scroll        |
| `.Item`             | `value`, `children`, `icon`, `description`, `wrapDescription` | The selected item's icon and label mirror into the trigger |
| `.Group` / `.Label` | Radix props                                                   | Uppercase group label                                      |
| `.Separator`        | `paddingParallel`, `paddingPerpendicular`                     | Opal `Divider`                                             |

Requires the `@radix-ui/react-select` peer dependency. The selected row uses the `select-heavy` selected tokens (`action-selection-01` background with the interactive foreground vars), and keyboard/hover highlight comes from Radix's `data-highlighted`.
