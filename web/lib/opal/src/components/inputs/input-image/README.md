# InputImage

**Import:** `import { InputImage, type InputImageProps } from "@opal/components";`

A circular image upload control: click or drag-and-drop (via `useImageDropzone` /
`react-dropzone`), an edit overlay on hover, and a compact remove button. Empty, filled, and
drag-active states each carry their own chrome. Labels come from `OpalStrings` (`image*`).

`tooltip` (`string | RichStr`) shows on hover, in any state. Inside `InputHorizontal` or
`InputVertical`, the row's `disabled` also disables it, and its `disabledTooltip` replaces `tooltip`
while disabled.
