# Dropdown

**Import:** `import { Dropdown } from "@opal/components";`

A floating list under a trigger. The dropdown handles positioning, the keyboard, search, groups and folding once, for every trigger. It is a compound: `Dropdown`, `Dropdown.Trigger`, `Dropdown.Anchor` and `Dropdown.Data`. The rows are data, never JSX.

The four input dropdowns (`InputSingleSelect`, `InputSingleComboBox`, `InputMultiSelect`, `InputMultiComboBox`) are built on it with a type-in trigger. No Radix: positioning is `@floating-ui/react-dom`.

## Usage

```tsx
import { Dropdown, InputTypeIn } from "@opal/components";

const [open, setOpen] = useState(false);
const [query, setQuery] = useState("");

<Dropdown open={open} onOpenChange={setOpen}>
  <Dropdown.Trigger asChild typeIn>
    <InputTypeIn
      value={query}
      onChange={(e) => {
        setQuery(e.target.value);
        setOpen(true);
      }}
    />
  </Dropdown.Trigger>
  <Dropdown.Data
    items={[
      { kind: "option", value: "apple", title: "Apple" },
      {
        kind: "group",
        title: "Citrus",
        foldable: true,
        items: [
          { kind: "option", value: "lemon", title: "Lemon" },
          { kind: "option", value: "lime", title: "Lime" },
        ],
      },
    ]}
    query={query}
    value={picked}
    onSelect={(option) => {
      setPicked(option.value);
      setOpen(false);
    }}
  />
</Dropdown>
```

## Parts

### `Dropdown`

| Prop           | Type                      | Default | Description                                                                 |
| -------------- | ------------------------- | ------- | --------------------------------------------------------------------------- |
| `open`         | `boolean`                 | —       | Controlled open state. Uncontrolled when left out.                          |
| `onOpenChange` | `(open: boolean) => void` | —       | Called with the next state                                                  |
| `disabled`     | `boolean`                 | `false` | Never opens and renders no list                                             |
| `id`           | `string`                  | auto    | Prefix for the list's and the rows' element ids, so a field can tie into it |

### `Dropdown.Trigger`

The element that holds focus and takes the keyboard. It carries `role="combobox"`, `aria-expanded`, `aria-controls` and `aria-activedescendant`. Opening and closing on click is the child's own behaviour: a button toggles, a type-in only opens.

| Prop      | Type      | Default | Description                                                                           |
| --------- | --------- | ------- | ------------------------------------------------------------------------------------- |
| `asChild` | `boolean` | `false` | Merge onto the child element. Without it, a `<button>` wraps the children             |
| `typeIn`  | `boolean` | `false` | The trigger is a text input whose text filters the list (pass it as `Data`'s `query`) |

### `Dropdown.Anchor`

The element the list positions against and matches in width, when that is not the trigger: a whole field whose trigger is one control inside it. Left out, the trigger anchors. `asChild` merges onto the child; without it, a `<div>` wraps the children.

### `Dropdown.Data`

| Prop                  | Type                                                    | Default | Description                                                                              |
| --------------------- | ------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------- |
| `items`               | `DropdownItem[]`                                        | —       | The rows: options and groups, in order                                                   |
| `label`               | `string`                                                | —       | The list's accessible name                                                               |
| `query`               | `string`                                                | —       | A type-in trigger's text; filters by title, value and `keywords`                         |
| `search`              | `{ placeholder; onChange? }`                            | —       | A search field pinned above the rows, for a trigger with nothing to type                 |
| `value`               | `string`                                                | —       | The selected value; its row reads as selected                                            |
| `values`              | `ReadonlySet<string>`                                   | —       | The selected values (multi); each reads as selected                                      |
| `exactText`           | `string`                                                | —       | Text whose exact match also reads as selected (a type-in's uncommitted pick)             |
| `highlightExactQuery` | `boolean`                                               | `false` | Move the highlight to the row the query matches exactly, unless the keyboard is driving  |
| `onSelect`            | `(option: DropdownOption) => void`                      | —       | A click or Enter on a row. What a pick means is the caller's                             |
| `create`              | `{ text; onCreate }`                                    | —       | A create row pinned first; shown only while given                                        |
| `otherOptionsTitle`   | `string`                                                | —       | Rows the query filtered out stay, under a group with this title                          |
| `maxHeight`           | `string`                                                | `15rem` | Max height of the list                                                                   |
| `onReachEnd`          | `(shown: DropdownOption[]) => void`                     | —       | The rows scrolled near their end, with the rows on show                                  |

## Items

```ts
type DropdownItem = DropdownOption | DropdownGroup;

interface DropdownOption {
  kind: "option";
  value: string;
  title: string;
  keywords?: string[];
  description?: string | RichStr;
  suffix?: string;
  icon?: IconFunctionComponent;
  disabled?: boolean;
}

interface DropdownGroup {
  kind: "group";
  title?: string;
  foldable?: boolean; // titled groups only
  items: DropdownOption[];
}
```

A loose option renders as a plain row. A group is a divider with the rows under it; a titled group may fold behind its title. A group whose rows all filter out disappears with its line.

## Keyboard

Focus stays on the trigger (or the search field); the dropdown moves a highlight and `aria-activedescendant` follows it. Enter or ArrowDown opens a closed list. Open, the arrows and Tab walk the stops and wrap, Enter picks the highlighted row or toggles a foldable title, and Escape closes. A trigger's own `onKeyDown` runs first; a key it cancels is left alone.

## Phase 1

This is the extracted core. Button triggers with click-to-toggle, action, toggle and custom rows, flyout submenus and width presets follow in later phases (see `plans/opal-dropdown.md`).
