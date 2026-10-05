# Dropdown

**Import:** `import { Dropdown } from "@opal/components";`

A floating list under a trigger. The dropdown handles positioning, the keyboard, search, groups and folding once, for every trigger. It is a compound: `Dropdown`, `Dropdown.Trigger`, `Dropdown.Anchor` and `Dropdown.Data`. The rows are data, never JSX; a row that needs its own rendering is a `custom` item.

With a `value` or `values`, `Dropdown.Data` is a **picker**: a `listbox` where something is selected. Without, it is a **menu**: commands, toggles and custom rows, and no `option` rows (a type error). No Radix: positioning is `@floating-ui/react-dom`.

The four input dropdowns are pickers built on it: the ComboBoxes (`InputSingleComboBox`, `InputMultiComboBox`) with a type-in trigger whose text filters the rows, the Selects (`InputSingleSelect`, `InputMultiSelect`) with an input-shaped button trigger and an optional search field in the list.

## Usage

A menu on a button:

```tsx
import { Dropdown, Button } from "@opal/components";

<Dropdown>
  <Dropdown.Trigger asChild>
    <Button icon={SvgMoreHorizontal} prominence="tertiary" />
  </Dropdown.Trigger>
  <Dropdown.Data
    label="Actions"
    search={{ placeholder: "Search" }}
    items={[
      {
        kind: "action",
        id: "rename",
        title: "Rename",
        icon: SvgEdit,
        onSelect: rename,
      },
      {
        kind: "toggle",
        id: "pin",
        title: "Pinned",
        checked: pinned,
        onCheckedChange: setPinned,
      },
      {
        kind: "group",
        title: "Danger zone",
        items: [
          {
            kind: "action",
            id: "delete",
            title: "Delete",
            danger: true,
            onSelect: remove,
          },
        ],
      },
    ]}
  />
</Dropdown>;
```

A picker on a type-in:

```tsx
<Dropdown open={open} onOpenChange={setOpen}>
  <Dropdown.Trigger asChild typeIn>
    <InputTypeIn
      aria-label="Fruit"
      value={query}
      onChange={(e) => setQuery(e.target.value)}
    />
  </Dropdown.Trigger>
  <Dropdown.Data
    label="Fruit"
    items={[
      { kind: "option", value: "apple", title: "Apple" },
      { kind: "group", title: "Citrus", foldable: true, items: [...] },
    ]}
    query={query}
    value={picked}
    onSelect={(option) => setPicked(option.value)}
  />
</Dropdown>
```

## Parts

### `Dropdown`

Left to itself the list sizes from its anchor: the anchor's width plus 6px on each side so the rows line up under the anchor's content, floored at `--block-width-dropdown-min` (17.5rem). `width` fixes it instead, in rem steps that include the 6px reach; `align` picks which anchor edge it lines up with, and it reaches 6px past that edge.

| Prop            | Type                                         | Default    | Description                                                                                                          |
| --------------- | -------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| `open`          | `boolean`                                    | —          | Controlled open state. Uncontrolled when left out.                                                                   |
| `onOpenChange`  | `(open: boolean) => void`                    | —          | Called with the next state                                                                                           |
| `disabled`      | `boolean`                                    | `false`    | Never opens and renders no list                                                                                      |
| `id`            | `string`                                     | auto       | Prefix for the list's and the rows' element ids, so a field can tie into it                                          |
| `virtualAnchor` | `{ getBoundingClientRect, contextElement? }` | —          | A rectangle to position against instead of an element, like a text caret                                             |
| `container`     | `HTMLElement \| null`                        | body       | Where the list portals to, for a dropdown inside a modal                                                             |
| `tabKey`        | `"walk" \| "leave"`                          | by trigger | What Tab does while open: walk the rows, or close and move on. Default: walk for a type-in, leave otherwise          |
| `width`         | `15 \| 17.5 \| 20 \| 22.5 \| 25`             | —          | A fixed width in rem, punch-out included; left out, the list matches its anchor                                      |
| `align`         | `"start" \| "end"`                           | `"start"`  | The anchor edge the list lines up with                                                                               |
| `side`          | `"bottom" \| "right"`                        | `"bottom"` | Below the anchor, or a flyout to its right (left when there is no room), its `align` edge lined up with the anchor's |

### `Dropdown.Trigger`

The element that holds focus and takes the keyboard. It carries `aria-expanded`, `aria-controls` and `aria-activedescendant`, `aria-haspopup` for the mode, and for a picker `role="combobox"`. A dropdown may have several triggers; the one that opened the list anchors it and takes focus back. A trigger that is the control inside an Opal field (an `InputTypeIn`'s `<input>`) anchors the list to the field's chrome.

| Prop       | Type                           | Default                           | Description                                                               |
| ---------- | ------------------------------ | --------------------------------- | ------------------------------------------------------------------------- |
| `asChild`  | `boolean`                      | `false`                           | Merge onto the child element. Without it, a `<button>` wraps the children |
| `typeIn`   | `boolean`                      | `false`                           | A text input whose text filters the list (pass it as `Data`'s `query`)    |
| `behavior` | `"toggle" \| "open" \| "none"` | `"open"` type-in, else `"toggle"` | What a click does; `"none"` leaves clicks to the child                    |

### `Dropdown.Anchor`

The element the list positions against and matches in width, when that is not the trigger: a whole field whose trigger is one control inside it, or a row opened from a button at its end. Left out, the trigger anchors. `asChild` merges onto the child; without it, a `<div>` wraps the children.

### `Dropdown.Data`

| Prop                  | Type                                                     | Default     | Description                                                                                                                                                                           |
| --------------------- | -------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `items`               | `DropdownItem[]` (picker) / `DropdownMenuItem[]`         | —           | The rows and groups, in order                                                                                                                                                         |
| `value`               | `string`                                                 | —           | Picker: the selected value                                                                                                                                                            |
| `values`              | `ReadonlySet<string>`                                    | —           | Picker: the selected values; the list stays open for more                                                                                                                             |
| `onSelect`            | `(option: DropdownOption, views: DropdownViews) => void` | —           | Picker: a click or Enter on an option                                                                                                                                                 |
| `closeOnSelect`       | `boolean`                                                | single only | Picker: close after a pick                                                                                                                                                            |
| `label`               | `string`                                                 | —           | The list's accessible name                                                                                                                                                            |
| `query`               | `string`                                                 | —           | A type-in trigger's text; filters by title, value and `keywords`                                                                                                                      |
| `search`              | `DropdownSearch`                                         | —           | A search field pinned above the rows, for a trigger with nothing to type: `InputTypeIn`'s props (`rightChildren`, `clearButton`, a test id…) plus `placeholder` and `onChange(query)` |
| `exactText`           | `string`                                                 | —           | Text whose exact match also reads as selected (a type-in's uncommitted pick)                                                                                                          |
| `highlightExactQuery` | `boolean`                                                | `false`     | Move the highlight to the option the query matches exactly, unless the keyboard drives                                                                                                |
| `create`              | `{ text; onCreate }`                                     | —           | A create row pinned first; shown only while given                                                                                                                                     |
| `otherOptionsTitle`   | `string`                                                 | —           | Rows the query filtered out stay, under a group with this title                                                                                                                       |
| `maxHeight`           | `string`                                                 | `15rem`     | Max height of the list                                                                                                                                                                |
| `noMatchText`         | `string`                                                 | Opal's      | What the list says when a search matches nothing                                                                                                                                      |
| `onReachEnd`          | `(shown: DropdownOption[]) => void`                      | —           | The rows scrolled near their end, with the options on show                                                                                                                            |
| `views`               | `Record<string, DropdownView>`                           | —           | Secondary views by key, rebuilt every render, so a view on the stack shows its latest rows                                                                                            |

## Items

| Kind     | Fields                                                                                                            | Enter                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `option` | `value`, `title`, `description?`, `descriptionMaxLines?`, `suffix?`, `icon?`                                      | `onSelect(option)`; closes (single)                                                                                  |
| `action` | `id`, `title`, `description?`, `icon?`, `danger?`, `keepOpen?`, and `onSelect(views)` and/or `href` (+ `target?`) | runs `onSelect`; an `href` row is a real link and navigates; closes unless `keepOpen` or the handler moved the stack |
| `toggle` | `id`, `title`, `description?`, `icon?`, `checked`, `onCheckedChange`                                              | flips `checked`; stays open                                                                                          |
| `custom` | `id`, `render(row)`, `onActivate?(views)`, `onSecondary?(views)`, `keepOpen?`                                     | `onActivate`; closes unless `keepOpen` or the handler moved the stack                                                |
| `group`  | `title?`, `foldable?` (titled only), `items`                                                                      | a foldable title folds and unfolds                                                                                   |

Every row takes `keywords?` (what a search matches beyond the title), `pinned?` (stays on show while a search is on: a way back, a create row) and `disabled?` (shown, but no stop and no clicks). A group whose rows all filter out disappears with its line.

### Custom rows

`render` gets `{ highlighted, props }`. Spread `props` onto the row's root: they carry the id, role, `data-index`, `tabIndex` and click handling that keep the row in the keyboard walk and under `aria-activedescendant`. Render `highlighted` as hover. Controls inside the row stop propagation themselves; the keyboard reaches one of them through `onSecondary` (ArrowRight). A custom row is searchable only by its `keywords`.

```tsx
{
  kind: "custom",
  id: `tool-${tool.id}`,
  keywords: [tool.name],
  onActivate: () => toggle(tool),
  onSecondary: () => openSettings(tool),
  render: ({ highlighted, props }) => (
    <LineItemButton presentational interaction={highlighted ? "hover" : "rest"} {...props} … />
  ),
}
```

## Views

A view is a set of menu rows that replaces the rows on show, in place: the old card slides out and the new one slides in, each at its own height. An action's `onSelect`, a custom row's `onActivate` and `onSecondary`, and a picker's `onSelect` get the stack as `views`, and `useDropdownViews()` returns the same object to a control rendered inside the list (a `Button` in a custom row, or in a toggle row's neighbour; a toggle's `onCheckedChange` itself gets only `checked`). Any such row pushes a view, under any logic it likes; the list stays open after a handler that pushed or popped.

```tsx
const skills: DropdownView = {
  key: "skills",
  search: { placeholder: "Search skills" },
  items: [
    {
      kind: "action",
      id: "back",
      title: "Back",
      icon: SvgChevronLeft,
      onSelect: (views) => views.pop(),
    },
    ...skillRows,
  ],
};
const items: DropdownMenuItem[] = [
  {
    kind: "action",
    id: "skills",
    title: "Skills",
    onSelect: (views) => views.push(skills),
  },
  {
    kind: "action",
    id: "apps",
    title: "Apps",
    onSelect: (views) => (authed ? views.push(apps) : startAuth()),
  },
];
```

| Field                  | Description                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `DropdownView.key?`    | Identifies the view on the stack; its depth when left out                                                                 |
| `DropdownView.items`   | The view's rows and groups                                                                                                |
| `DropdownView.search?` | A search field pinned above the view's rows. It filters this view only, and keeps its text while the view is on the stack |
| `DropdownView.width?`  | The list's width while this view is on top; else the list's own                                                           |
| `DropdownViews.push`   | Replace the rows with a view: a key from `views`, or an object (refreshed from `views` when its `key` is there)           |
| `DropdownViews.pop`    | Back one view; nothing at the root                                                                                        |
| `DropdownViews.close`  | Close the list                                                                                                            |

Build views that hold state (a toggle, search results) in render and pass them through `views`, so the stack always shows the latest rows; a pushed object is a snapshot otherwise. Views are menu rows: push them from a menu. A view pushed from a picker renders under the picker's listbox roles. Nothing is laid out for a view: a way back is a row that calls `pop`. The root-only props (`query`, `create`, `otherOptionsTitle`, `exactText`) wait underneath a view. Escape leaves a view; at the root it closes. Closing the list empties the stack. Each search field reports `""` through its `onChange` as its rows leave.

## Keyboard

Focus stays on the trigger (or the search field); the dropdown moves a highlight and `aria-activedescendant` follows it. Enter or ArrowDown opens a closed list. Open, the arrows walk the stops and wrap, Enter activates the highlighted stop, ArrowRight reaches a custom row's secondary control, and Escape leaves a view or closes. A trigger's own `onKeyDown` runs first; a key it cancels is left alone. A view opened from the keyboard highlights its first row; leaving it from the keyboard returns the highlight to the row that led in.

**Tab** depends on the trigger: from a type-in it walks the rows like the arrows, since the field must keep focus; from any other trigger it closes the list and lets focus move on, as a native menu does. `tabKey` on `Dropdown` fixes it one way for every trigger.

**Groups, from a trigger with nothing to type into:** ArrowRight on a folded title unfolds it; on an open title it moves to the first row inside. A text field (a type-in, or the search field) keeps the key for its caret.

**Type-ahead:** on a trigger with nothing to type into, letters jump the highlight to the next row whose title starts with them; the letters clear after half a second. A custom row matches on its first keyword. A type-in's letters are its filter instead, and a search field's go to the field.

## Still to come

The migration of the app's menus (phase 4); see `plans/opal-dropdown.md`.
