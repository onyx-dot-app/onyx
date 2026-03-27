import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import Modal from "./Modal";
import { Button } from "@opal/components";
import { SvgInfoSmall } from "@opal/icons";

const meta: Meta<typeof Modal> = {
  title: "refresh-components/Modal",
  component: Modal,
  tags: ["autodocs"],
  parameters: {
    layout: "fullscreen",
  },
};

export default meta;
type Story = StoryObj<typeof Modal>;

function ModalDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ padding: 32 }}>
      <Button onClick={() => setOpen(true)}>Open Modal</Button>
      <Modal open={open} onOpenChange={setOpen}>
        <Modal.Content width="sm" height="fit">
          <Modal.Header
            icon={SvgInfoSmall}
            title="Example Modal"
            description="This is a demo modal with header, body, and footer."
            onClose={() => setOpen(false)}
          />
          <Modal.Body>
            <div style={{ padding: 16 }}>
              Some body content goes here. You can put forms, text, or anything
              else inside the modal body.
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="default"
              prominence="secondary"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="action"
              prominence="primary"
              onClick={() => setOpen(false)}
            >
              Confirm
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </div>
  );
}

export const Default: Story = {
  render: () => <ModalDemo />,
};

function LargeModalDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ padding: 32 }}>
      <Button onClick={() => setOpen(true)}>Open Large Modal</Button>
      <Modal open={open} onOpenChange={setOpen}>
        <Modal.Content width="full" height="full">
          <Modal.Header
            icon={SvgInfoSmall}
            title="Large Modal"
            description="A large modal with full height."
            onClose={() => setOpen(false)}
          />
          <Modal.Body>
            <div style={{ padding: 16 }}>
              {Array.from({ length: 20 }, (_, i) => (
                <p key={i} style={{ marginBottom: 12 }}>
                  Paragraph {i + 1}: Lorem ipsum dolor sit amet, consectetur
                  adipiscing elit. Sed do eiusmod tempor incididunt ut labore et
                  dolore magna aliqua.
                </p>
              ))}
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="default"
              prominence="secondary"
              onClick={() => setOpen(false)}
            >
              Close
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </div>
  );
}

export const Large: Story = {
  render: () => <LargeModalDemo />,
};

function GrayBackgroundDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ padding: 32 }}>
      <Button onClick={() => setOpen(true)}>Open Gray Modal</Button>
      <Modal open={open} onOpenChange={setOpen}>
        <Modal.Content width="sm" height="fit" background="gray">
          <Modal.Header
            icon={SvgInfoSmall}
            title="Gray Background"
            description="This modal uses background='gray' for a tinted card."
            onClose={() => setOpen(false)}
          />
          <Modal.Body>
            <div style={{ padding: 16 }}>
              The modal card background uses the tinted color variant.
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="default"
              prominence="secondary"
              onClick={() => setOpen(false)}
            >
              Close
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </div>
  );
}

export const GrayBackground: Story = {
  render: () => <GrayBackgroundDemo />,
};

function NoOverlayDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ padding: 32 }}>
      <Button onClick={() => setOpen(true)}>Open Without Overlay</Button>
      <Modal open={open} onOpenChange={setOpen}>
        <Modal.Content width="sm" height="fit" skipOverlay>
          <Modal.Header
            icon={SvgInfoSmall}
            title="No Overlay"
            description="This modal skips the backdrop overlay."
            onClose={() => setOpen(false)}
          />
          <Modal.Body>
            <div style={{ padding: 16 }}>
              The page behind remains fully visible with no blur or mask.
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button
              variant="default"
              prominence="secondary"
              onClick={() => setOpen(false)}
            >
              Close
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </div>
  );
}

export const NoOverlay: Story = {
  render: () => <NoOverlayDemo />,
};
