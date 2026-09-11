# InputList

**Import:** `import { InputList, type InputListProps } from "@opal/components";`

A list-of-strings input: type a value, press Enter, and it lands as a removable `Tag` chip below
the field. Duplicates are ignored; IME composition is respected. Unlike `InputMultiSelect`, the chips
render _under_ the input rather than inline within it — use this when the list is the content and
the field is just the entry point (e.g. a list of domains or scopes in a form).

## Props

| Prop          | Type                         | Default | Description                     |
| ------------- | ---------------------------- | ------- | ------------------------------- |
| `values`      | `string[]`                   | —       | The list to display             |
| `onChange`    | `(values: string[]) => void` | —       | Fires with the updated list     |
| `placeholder` | `string`                     | `""`    | Input placeholder               |
| `disabled`    | `boolean`                    | `false` | Disables input and chip removal |
| `error`       | `boolean`                    | `false` | Error chrome on the input       |
