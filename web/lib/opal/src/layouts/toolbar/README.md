# Toolbar

**Import:** `import { Toolbar, type ToolbarProps } from "@opal/layouts";`

A row of a search field, filters and actions above a list or table. The search field takes most of the
row, each filter takes a smaller share, and the actions keep their width. On a narrow page the items
wrap to new lines.

## Props

| Prop      | Type          | Default | Description                                                   |
| --------- | ------------- | ------- | ------------------------------------------------------------- |
| `search`  | `ReactNode`   | —       | The search field, usually `InputTypeIn` with `icon="search"`  |
| `filters` | `ReactNode[]` | `[]`    | Filter inputs after the search field, such as `InputSingleSelect` |
| `actions` | `ReactNode`   | —       | Controls at the end of the row, such as bulk actions          |

## Usage

```tsx
<Toolbar
  search={<InputTypeIn icon="search" value={query} onChange={…} />}
  filters={[<InputSingleSelect key="type" … />]}
  actions={selected > 0 && <Button>Share</Button>}
/>
```
