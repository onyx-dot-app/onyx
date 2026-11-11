# ConfirmationModalLayout

**Import:** `import { ConfirmationModalLayout } from "@opal/layouts";`

A prebuilt small confirm dialog composed on the `Modal` component: icon header, body copy, and a footer with Cancel plus a caller-supplied submit action. This is a layout, it arranges `Modal` pieces into a fixed confirm arrangement rather than adding new chrome.

It renders open, so mount it inside the `Provider` from `useCreateModal`. When `onClose` is passed, the caller owns closing: the callback must close the owner (e.g. `modal.toggle(false)`) when closing is allowed, and can decline, for example while a request runs. Pass `onClose={undefined}` to hide Cancel and the X and block Escape and overlay clicks. Omit `onClose` to let the owner close it.

## Props

| Prop          | Type                    | Default        | Description                                                   |
| ------------- | ----------------------- | -------------- | ------------------------------------------------------------- |
| `icon`        | `IconFunctionComponent` | **(required)** | Header icon                                                   |
| `color`       | `StatusColor \| "interactive"` | `"default"`    | Colour mode of the header icon and title, as on `Content`     |
| `title`       | `string \| RichStr`     | **(required)** | Header title                                                  |
| `description` | `string \| RichStr`     | —              | Header description                                            |
| `submit`      | `ReactNode`             | **(required)** | Confirm action, rendered in the footer after Cancel           |
| `children`    | `ReactNode`             | —              | Body content. Plain strings render as `text-03` body copy     |
| `hideCancel`  | `boolean`               | `false`        | Hides the Cancel button (leaves only `submit`)                |
| `onClose`     | `() => void`            | —              | Closes the modal; it must close the owner itself. `undefined` blocks closing; omitted, the owner closes it |
| `twoTone`     | `boolean`               | `true`         | Gray body background separating it from the header and footer |

## Usage

```tsx
import { Button, useCreateModal } from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import SvgTrash from "@opal/icons/trash";

function DeleteButton() {
  const modal = useCreateModal();
  return (
    <>
      <Button onClick={() => modal.toggle(true)}>Delete item</Button>
      <modal.Provider>
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete item"
          description="This cannot be undone."
          submit={
            <Button variant="danger" onClick={() => modal.toggle(false)}>
              Delete
            </Button>
          }
        >
          The item and its history will be removed for every member.
        </ConfirmationModalLayout>
      </modal.Provider>
    </>
  );
}
```
