import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { BasicModalFooter, Button, Modal } from "@opal/components";
import { SvgSettings, SvgTrash } from "@opal/icons";

const meta: Meta<typeof Modal.Content> = {
  title: "opal/components/Modal",
  component: Modal.Content,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Modal.Content>;

function ModalHarness({
  children,
  label = "Open modal",
}: {
  children: (close: () => void) => React.ReactNode;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>{label}</Button>
      <Modal open={open} onOpenChange={setOpen}>
        {children(() => setOpen(false))}
      </Modal>
    </>
  );
}

export const Default: Story = {
  render: () => (
    <ModalHarness>
      {(close) => (
        <Modal.Content width="md">
          <Modal.Header
            icon={SvgSettings}
            title="Modal title"
            description="Supporting description for the modal."
            onClose={close}
          />
          <Modal.Body>Body content lives here.</Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button prominence="secondary" onClick={close}>
                  Cancel
                </Button>
              }
              submit={<Button onClick={close}>Confirm</Button>}
            />
          </Modal.Footer>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

export const MinimalHeader: Story = {
  render: () => (
    <ModalHarness label="Open preview modal">
      {(close) => (
        <Modal.Content width="sm">
          <Modal.Header title="Preview" onClose={close} />
          <Modal.Body twoTone={false}>
            Minimal header variant without an icon.
          </Modal.Body>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

export const DangerFooter: Story = {
  render: () => (
    <ModalHarness label="Open delete modal">
      {(close) => (
        <Modal.Content width="sm">
          <Modal.Header
            icon={SvgTrash}
            title="Delete item"
            description="This cannot be undone."
            onClose={close}
          />
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button prominence="secondary" onClick={close}>
                  Cancel
                </Button>
              }
              submit={
                <Button variant="danger" onClick={close}>
                  Delete
                </Button>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

export const TopPosition: Story = {
  render: () => (
    <ModalHarness label="Open top-pinned modal">
      {(close) => (
        <Modal.Content width="md" position="top">
          <Modal.Header title="Command palette position" onClose={close} />
          <Modal.Body>Pinned near the top of the viewport.</Modal.Body>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};
