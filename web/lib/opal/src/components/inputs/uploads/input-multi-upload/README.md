# InputMultiUpload

**Import:** `import { InputMultiUpload, type InputMultiUploadProps } from "@opal/components";`
**Formik:** `import { InputMultiUploadField } from "@opal/form";`

An upload control for many files. Each file is a removable tag inside the input chrome, as on
`InputMultiSelect` (it uses the same `TagField`). A click on the field, or Enter or Space, opens the
file picker, and files can be dropped on it. Each pick or drop **adds** files, skipping ones it
already holds. Backspace arms the last tag and Backspace or Delete removes an armed one; the clear
button removes them all.

The drop states follow [InputSingleUpload](../input-single-upload/README.md): while files are dragged
over the page the field shows itself as a drop target, darker over the field itself.

| Drag             | Empty                    | Holding files                 |
| ---------------- | ------------------------ | ----------------------------- |
| Over the page    | "Drop files here to add" | the tags                      |
| Over the control | "Drop files here to add" | "Drop here to add more files" |

A dropped file must match `accept`, and is refused above `maxSizeKb`, as a picked one is. Opening the
picker does not count as leaving the field, so a form does not mark it touched mid-pick.

## Props

| Prop                 | Type                            | Description                                                      |
| -------------------- | ------------------------------- | ---------------------------------------------------------------- |
| `value`              | `File[]`                        | The files, when the caller owns them                             |
| `onFilesChange`      | `(files: File[]) => void`       | Receives every file held, after each add or removal              |
| `placeholder`        | `string`                        | Shown while empty. Default: "Add files…"                         |
| `variant`            | `InputVariants`                 | `"primary"` (default), `"error"`, `"disabled"`, `"readOnly"`      |
| `accept`             | `string`                        | The picker's filter, as the HTML `accept` attribute               |
| `maxSizeKb`          | `number`                        | Rejects a file larger than this                                  |
| `onFileSizeExceeded` | `({ file, maxSizeKb }) => void` | Called when a file is rejected for its size                      |
| `id`, `name`, `onBlur`, `data-testid` | —              | `id` goes on the hidden file input, so a field label opens the picker |

`InputMultiUploadField` binds it to a Formik `File[]` field, holding `null` when empty so a required
check fails.

Labels come from `OpalStrings`: `inputMultiUploadPlaceholder`, `inputMultiUploadDropToAdd` and
`inputMultiUploadDropToAddMore`.

## Usage

```tsx
<InputMultiUpload value={files} onFilesChange={setFiles} />

<InputMultiUploadField name="file_locations" />
```
