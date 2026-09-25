# InputSingleSelect

**Import:** `import { InputSingleSelect, type InputSingleSelectProps, type SelectOption, type SelectDivider, type SelectOptions } from "@opal/components";`

A single pick from a set, with nothing to type. The trigger is an input-shaped
button: like a native `<select>`, a click or ArrowDown opens the full set, a
second click closes it, and keyboard focus alone does not open it. Keyboard
navigation (arrows, Enter, Escape) and ARIA combobox semantics are built in.
The type-in sibling is [InputSingleComboBox](../input-single-combo-box/README.md).

Re-picking the selected option unselects it (the value becomes `""` and the
placeholder shows).

## Default option

With `defaultOption` the select never reads as empty: an empty `value` resolves
to it, and re-picking the selected option does nothing, like a native
`<select>`. `onValueChange` never receives `""`.
`placeholder` stays required: it is the field's accessible name even when the
default keeps the trigger filled.

`options` is a list of loose options and dividers in any order, like
`<option>`s beside `<optgroup>`s: a divider is `{ title?, options }` and renders
a separator line above its rows, carrying `title` when there is one. The trigger shows the chosen option's `icon`, when it has one. A value
outside the set shows the placeholder with the validation error.

```tsx
<InputSingleSelect
  value={strategy}
  onValueChange={setStrategy}
  defaultOption="reindex"
  placeholder="Select a strategy"
  options={[
    { options: [{ value: "none", title: "Do not re-index" }] },
    {
      title: "Re-index options",
      options: [
        { value: "reindex", title: "Re-index all, then switch" },
        { value: "instant", title: "Switch, then re-index" },
      ],
    },
  ]}
/>
```

## Keyboard

The trigger is a button: a click, Enter or ArrowDown opens the list,
and a second click closes it. Open, the arrows and Tab walk the stops in
order and wrap around: a foldable divider's title is a stop of its own, then
its rows, and with `search` the search field is the stop before the first
row. Enter picks the highlighted row or toggles the highlighted title;
Escape closes and returns focus to the trigger. Disabled rows are passed
over. Physical focus stays on the
trigger or the search field, and `aria-activedescendant` follows the
highlight. Typing in the search field never highlights a row; only walking
the list does. A title stop has no highlight of its own yet: its hover and
press come from the Divider's `Interactive`.

Foldable groups start closed, except the one holding the selection; with
nothing selected, every group starts closed.

## Search

With `search` a search field sits at the top of the list and filters the
rows by title or value; a term that matches a divider's title keeps that
whole section. It takes focus when the list opens, so typing starts at once;
arrows, Enter, Escape and Tab work from it as from the trigger. Escape closes
the list and returns focus to the trigger; Tab closes it and moves on to the
next field, as it would from the trigger.

## Foldable dividers

A titled divider with `foldable: true` folds its rows behind the title. It
starts closed unless it holds the selection, and starts open while a search
is on so no match hides; either way a click on the title toggles it. Toggles
reset when the search starts or stops and when the list closes. Folded rows
leave the keyboard order.

```tsx
<InputSingleSelect
  search
  placeholder="Select a model"
  value={model}
  onValueChange={setModel}
  options={providers.map((provider) => ({
    title: provider.name,
    foldable: true,
    options: provider.models,
  }))}
/>
```

## Props

| Prop            | Type                                | Default | Description                                                     |
| --------------- | ----------------------------------- | ------- | --------------------------------------------------------------- |
| `value`         | `string`                            | —       | Current value (controlled)                                      |
| `onValueChange` | `(value: string) => void`           | —       | Fires on a pick, and with `""` on an unpick                     |
| `options`       | `SelectOptions` | `[]`    | Loose options and dividers, in order                        |
| `search`    | `boolean`                           | `false` | A search field at the top of the list filters the rows          |
| `defaultOption` | `string`                            | —       | Option value an empty `value` resolves to; never empties then   |
| `placeholder`   | `string`                            | —       | Shown while empty; always the accessible name (required)        |
| `isError`       | `boolean`                           | —       | External error state (overrides internal validation)            |
| `rightChildren` | `React.ReactNode`                   | —       | Extra trigger-side controls                                     |

Formik: `InputSingleSelectField` from `@opal/form`.
