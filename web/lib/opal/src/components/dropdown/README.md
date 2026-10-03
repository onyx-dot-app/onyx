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
      { kind: "action", id: "rename", title: "Rename", icon: SvgEdit, onSelect: rename },
      { kind: "toggle", id: "pin", title: "Pinned", checked: pinned, onCheckedChange: setPinned },
      {
        kind: "group",
        title: "Danger zone",
        items: [{ kind: "action", id: "delete", title: "Delete", danger: true, onSelect: remove }],
      },
    ]}
  />
</Dropdown>
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

The list is always its anchor's width, 6px wider on each side so the rows line up under the anchor's content, and never narrower than `--block-width-dropdown-min` (17.5rem), so a narrow button trigger still gets a usable list.

| Prop            | Type                                       | Default    | Description                                                                 |
| --------------- | ------------------------------------------ | ---------- | --------------------------------------------------------------------------- |
| `open`          | `boolean`                                  | —          | Controlled open state. Uncontrolled when left out.                          |
| `onOpenChange`  | `(open: boolean) => void`                  | —          | Called with the next state                                                  |
| `disabled`      | `boolean`                                  | `false`    | Never opens and renders no list                                             |
| `id`            | `string`                                   | auto       | Prefix for the list's and the rows' element ids, so a field can tie into it |
| `virtualAnchor` | `{ getBoundingClientRect, contextElement? }` | —        | A rectangle to position against instead of an element, like a text caret   |
| `container`     | `HTMLElement \| null`                      | body       | Where the list portals to, for a dropdown inside a modal                    |
| `tabKey`        | `"walk" \| "leave"`                        | by trigger | What Tab does while open: walk the rows, or close and move on. Default: walk for a type-in, leave otherwise |

### `Dropdown.Trigger`

The element that holds focus and takes the keyboard. It carries `aria-expanded`, `aria-controls` and `aria-activedescendant`, `aria-haspopup` for the mode, and for a picker `role="combobox"`. A dropdown may have several triggers; the one that opened the list anchors it and takes focus back. A trigger that is the control inside an Opal field (an `InputTypeIn`'s `<input>`) anchors the list to the field's chrome.

| Prop       | Type                              | Default                   | Description                                                                   |
| ---------- | --------------------------------- | ------------------------- | ----------------------------------------------------------------------------- |
| `asChild`  | `boolean`                         | `false`                   | Merge onto the child element. Without it, a `<button>` wraps the children     |
| `typeIn`   | `boolean`                         | `false`                   | A text input whose text filters the list (pass it as `Data`'s `query`)        |
| `behavior` | `"toggle" \| "open" \| "none"`    | `"open"` type-in, else `"toggle"` | What a click does; `"none"` leaves clicks to the child                 |

### `Dropdown.Anchor`

The element the list positions against and matches in width, when that is not the trigger: a whole field whose trigger is one control inside it, or a row opened from a button at its end. Left out, the trigger anchors. `asChild` merges onto the child; without it, a `<div>` wraps the children.

### `Dropdown.Data`

| Prop                  | Type                                                | Default     | Description                                                                             |
| --------------------- | --------------------------------------------------- | ----------- | --------------------------------------------------------------------------------------- |
| `items`               | `DropdownItem[]` (picker) / `DropdownMenuItem[]`    | —           | The rows and groups, in order                                                           |
| `value`               | `string`                                            | —           | Picker: the selected value                                                              |
| `values`              | `ReadonlySet<string>`                               | —           | Picker: the selected values; the list stays open for more                               |
| `onSelect`            | `(option: DropdownOption) => void`                  | —           | Picker: a click or Enter on an option                                                   |
| `closeOnSelect`       | `boolean`                                           | single only | Picker: close after a pick                                                              |
| `label`               | `string`                                            | —           | The list's accessible name                                                              |
| `query`               | `string`                                            | —           | A type-in trigger's text; filters by title, value and `keywords`                        |
| `search`              | `{ placeholder; onChange? }`                        | —           | A search field pinned above the rows, for a trigger with nothing to type                |
| `exactText`           | `string`                                            | —           | Text whose exact match also reads as selected (a type-in's uncommitted pick)            |
| `highlightExactQuery` | `boolean`                                           | `false`     | Move the highlight to the option the query matches exactly, unless the keyboard drives  |
| `create`              | `{ text; onCreate }`                                | —           | A create row pinned first; shown only while given                                       |
| `otherOptionsTitle`   | `string`                                            | —           | Rows the query filtered out stay, under a group with this title                         |
| `maxHeight`           | `string`                                            | `15rem`     | Max height of the list                                                                  |
| `onReachEnd`          | `(shown: DropdownOption[]) => void`                 | —           | The rows scrolled near their end, with the options on show                              |

## Items

| Kind     | Fields                                                                       | Enter                                    |
| -------- | ---------------------------------------------------------------------------- | ---------------------------------------- |
| `option` | `value`, `title`, `description?`, `suffix?`, `icon?`                          | `onSelect(option)`; closes (single)      |
| `action` | `id`, `title`, `description?`, `icon?`, `danger?`, `keepOpen?`, and `onSelect` and/or `href` (+ `target?`) | runs `onSelect`; an `href` row is a real link and navigates; closes unless `keepOpen` |
| `toggle` | `id`, `title`, `description?`, `icon?`, `checked`, `onCheckedChange`          | flips `checked`; stays open              |
| `custom` | `id`, `render(row)`, `onActivate?`, `onSecondary?`, `keepOpen?`               | `onActivate`; closes unless `keepOpen`   |
| `group`  | `title?`, `foldable?` (titled only), `items`                                  | a foldable title folds and unfolds       |

Every row takes `keywords?` (what a search matches beyond the title) and `disabled?` (shown, but no stop and no clicks). A group whose rows all filter out disappears with its line.

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

## Keyboard

Focus stays on the trigger (or the search field); the dropdown moves a highlight and `aria-activedescendant` follows it. Enter or ArrowDown opens a closed list. Open, the arrows walk the stops and wrap, Enter activates the highlighted stop, ArrowRight reaches a custom row's secondary control, and Escape closes. A trigger's own `onKeyDown` runs first; a key it cancels is left alone.

**Tab** depends on the trigger: from a type-in it walks the rows like the arrows, since the field must keep focus; from any other trigger it closes the list and lets focus move on, as a native menu does. `tabKey` on `Dropdown` fixes it one way for every trigger.

**Type-ahead:** on a trigger with nothing to type into, letters jump the highlight to the next row whose title starts with them; the letters clear after half a second. A custom row matches on its first keyword. A type-in's letters are its filter instead, and a search field's go to the field.

## Still to come

Flyout submenus (phase 3) and the migration of the app's menus (phase 4); see `plans/opal-dropdown.md`.
