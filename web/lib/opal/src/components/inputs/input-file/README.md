# InputFile

**Import:** `import { InputFile, type InputFileProps } from "@opal/components";`

A text field that doubles as a file picker: type a value directly, or attach a file via the
paperclip action and the field displays the file's name and carries its text content. Clearing
returns to typed mode. Built on `InputTypeIn`; the attach/clear actions are `Button`s in the
right slot.

## Props

Extends `InputTypeInProps` (minus `value`/`onChange` internals), plus:

| Prop                 | Type                            | Description                                            |
| -------------------- | ------------------------------- | ------------------------------------------------------ |
| `setValue`           | `(value: string) => void`       | Receives the typed text or the selected file's content |
| `onValueSet`         | callback                        | Fires after a value lands                              |
| `accept`             | `string`                        | File-picker accept filter                              |
| `maxSizeKb`          | `number`                        | Reject files above this size                           |
| `onFileSizeExceeded` | `({ file, maxSizeKb }) => void` | Called when a file is rejected for size                |

The attach/clear aria labels come from `OpalStrings` (`attachFile` / `clearFile`).
