# InputUpload

**Import:** `import { InputUpload, type InputUploadProps } from "@opal/components";`
**Formik:** `import { InputUploadField } from "@opal/form";`

An upload control in the input chrome, for one file in a form row. Nothing is typed: a click, Enter
or Space opens the file picker, and a file can be dropped on it. It leads with an import icon, shows
the placeholder until a file is in, then the file's name, with a × at the end that clears it.

While files are dragged anywhere over the page (`useWindowFileDrag` from `@opal/hooks`), the control
shows itself as a drop target: a dashed `action-selection-05` border, `action-selection-01` fill, and
blue icon and text. Over the control itself the fill deepens to `action-selection-02`. The × hides
during a drag. The copy says what a drop does:

| Drag            | Empty                   | Holding a file              |
| --------------- | ----------------------- | --------------------------- |
| Over the page   | "Drop file here to add" | the file's name             |
| Over the control | "Drop file here to add" | "Drop here to replace file" |

A dropped file must match `accept`, and is refused above `maxSizeKb`, as a picked one is.

## Modes

- **`mode="text"`** (default): the value is the file's **text** (`setValue`), for text files such as a
  JSON key. Focused, the control also takes a paste (Cmd/Ctrl+V); the pasted text becomes the value
  and the control shows "Pasted text".
- **`mode="file"`**: the value is the **`File`** itself, unread (`onFileChange`), for a binary file
  such as a `.pfx` certificate. No paste.

## Props

| Prop                 | Mode | Type                            | Description                                                                 |
| -------------------- | ---- | ------------------------------- | --------------------------------------------------------------------------- |
| `mode`               | both | `"text" \| "file"`              | Default `"text"`                                                            |
| `value`              | text | `string`                        | The value, when the caller owns it. Set from outside, it shows "File attached" |
| `setValue`           | text | `(value: string) => void`       | Receives the file's text or the pasted text; `""` once cleared              |
| `value`              | file | `File \| null`                  | The file, when the caller owns it                                           |
| `onFileChange`       | file | `(file: File \| null) => void`  | Receives the file, or `null` once cleared                                   |
| `variant`            | both | `InputVariants`                 | `"primary"` (default), `"error"`, `"disabled"` (no picking, dropping or pasting), `"readOnly"` |
| `placeholder`        | both | `string`                        | Shown while empty; also the control's accessible name                       |
| `accept`             | both | `string`                        | The picker's filter, as the HTML `accept` attribute; a drop must match it   |
| `maxSizeKb`          | both | `number`                        | Rejects a file larger than this                                             |
| `onFileSizeExceeded` | both | `({ file, maxSizeKb }) => void` | Called when a file is rejected for its size                                 |
| `id`, `name`, `onBlur`, `data-testid` | both | —              | Passed to the control (`name` to the hidden file input)                     |

Without `value`, the control keeps its own. `InputUploadField` binds it to Formik: a `string` field in
text mode, a `File | null` field in file mode. An upload, paste or clear marks the field touched; a
touched field with an error shows the error variant.

Labels come from `OpalStrings`: `attachFile`, `clearFile`, `inputUploadPasted`, `inputUploadAttached`,
`inputUploadDropToAdd` and `inputUploadDropToReplace`.

## Usage

```tsx
<InputUpload accept="application/json" placeholder="Upload a key file" setValue={setKey} />

<InputUpload mode="file" accept=".pfx" onFileChange={setCertificate} />

<InputUploadField name="apiKey" accept=".json" />
```
