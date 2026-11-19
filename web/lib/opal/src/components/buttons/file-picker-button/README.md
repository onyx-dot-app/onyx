# FilePickerButton

**Import:** `import { FilePickerButton, type FilePickerButtonProps } from "@opal/components";`

A `Button` that opens the file picker and takes files and folders dropped on it. It renders the hidden
file input itself, so callers need no raw `<input>`. A dropped folder's files keep their folder path in
`path`. For a field that holds files, with drop and paste, use `InputSingleUpload` or
`InputMultiUpload` instead.

## Props

Takes every `Button` prop except `onClick`, `href` and `type`, plus:

| Prop         | Type                      | Default | Description                                                  |
| ------------ | ------------------------- | ------- | ------------------------------------------------------------ |
| `inputLabel` | `string`                  | —       | Accessible name of the file input; tests select it by this   |
| `multiple`   | `boolean`                 | `true`  | Whether several files can be picked                          |
| `onFiles`    | `(files: File[]) => void` | —       | Receives the picked or dropped files                         |

## Usage

```tsx
<FilePickerButton
  icon={SvgPlus}
  prominence="tertiary"
  inputLabel="Add skill files"
  onFiles={(files) => void add(files)}
>
  Add File
</FilePickerButton>
```
