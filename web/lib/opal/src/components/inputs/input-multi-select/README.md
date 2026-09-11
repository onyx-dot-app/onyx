# InputMultiSelect

**Import:** `import { InputMultiSelect, type InputMultiSelectProps, type InputMultiSelectItem } from "@opal/components";`

Searchable multi-select on a tinted container: a search input opens a
dropdown of options, and the current selection lives in a list below it.
Clicking a dropdown row toggles it; clicking a selected row removes it.
While nothing is selected, the list shows an `EmptyMessageCard`.

Controlled only — pair it with `InputMultiSelectField` from `@opal/form`
inside a Formik form:

```tsx
<InputMultiSelectField
  name="group_ids"
  items={groups.map((g) => ({
    id: String(g.id),
    title: g.name,
    description: t("memberCount", { count: g.users.length }),
    icon: SvgUsers,
  }))}
  placeholder={t("search.placeholder")}
  removeIcon={SvgLogOut}
  container={modalContentEl}
/>
```

## Props

| Prop          | Type                          | Default  | Description                                                       |
| ------------- | ----------------------------- | -------- | ----------------------------------------------------------------- |
| `items`       | `InputMultiSelectItem[]`      | —        | Full option set; filtered internally by title (case-insensitive)  |
| `value`       | `string[]`                    | —        | Selected item ids (controlled)                                    |
| `onChange`    | `(next: string[]) => void`    | —        | Next selected-id set on every toggle or removal                   |
| `placeholder` | `string`                      | —        | Search input placeholder                                          |
| `disabled`    | `boolean`                     | —        | Disables the input, dropdown, and rows                            |
| `loading`     | `boolean`                     | —        | Loading row in the dropdown instead of options                    |
| `removeIcon`  | `IconFunctionComponent`       | `SvgX`   | Trailing icon on selected rows (e.g. `SvgLogOut` for memberships) |
| `container`   | `HTMLElement \| null`         | —        | Dropdown portal container (a modal's content element)             |

Unlisted props are DOM and reach the search input, so `data-testid` hooks
land on the element tests drive.

`InputMultiSelectItem`: `{ id: string; title; description?; icon? }`. `title`
is also the filter target. Selected dropdown rows show a check in place of
the item icon.

## Out of scope

Grouped options, async search, and create-new (`InputComboBox`'s territory);
chips-style display (`AddPeoplePicker`). Number ids: callers `String()` them.
