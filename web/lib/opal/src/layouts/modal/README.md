# ConfirmationModalLayout

**Import:** `import { ConfirmationModalLayout } from "@opal/layouts";`

A prebuilt small confirm dialog composed on the `Modal` component: icon header, body copy, and a footer with Cancel plus a caller-supplied submit action. This is a layout, it arranges `Modal` pieces into a fixed confirm arrangement rather than adding new chrome.

It renders open, so mount it inside the `Provider` from `useCreateModal`. Closing is routed through `useModalClose`.

## Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `icon` | `IconFunctionComponent` | **(required)** | Header icon |
| `title` | `string \| RichStr` | **(required)** | Header title |
| `description` | `string \| RichStr` | — | Header description |
| `submit` | `ReactNode` | **(required)** | Confirm action, rendered in the footer after Cancel |
| `children` | `ReactNode` | — | Body content. Plain strings render as `text-03` body copy |
| `hideCancel` | `boolean` | `false` | Hides the Cancel button (leaves only `submit`) |
| `onClose` | `() => void` | — | Runs when the modal closes, composed via `useModalClose` |
| `twoTone` | `boolean` | `true` | Gray body background separating it from the header and footer |

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
