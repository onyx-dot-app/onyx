import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import ConfirmationModalLayout from "./ConfirmationModalLayout";
import { SvgAlertTriangle, SvgTrash, SvgCheckCircle } from "@opal/icons";
import { Button } from "@opal/components";

const meta: Meta<typeof ConfirmationModalLayout> = {
  title: "refresh-components/modals/ConfirmationModalLayout",
  component: ConfirmationModalLayout,
  tags: ["autodocs"],
  parameters: {
    layout: "fullscreen",
  },
};

export default meta;
type Story = StoryObj<typeof ConfirmationModalLayout>;

/**
 * NOTE: ConfirmationModalLayout calls `useModalClose` internally, which reads
 * from ModalContext. Outside of that context, it falls back to the `onClose`
 * prop, so these stories work without wrapping in a ModalContext provider.
 */

export const DeleteConfirmation: Story = {
  render: () => {
    const [open, setOpen] = useState(true);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open Modal</button>
        {open && (
          <ConfirmationModalLayout
            icon={SvgTrash}
            title="Delete Item"
            description="Are you sure you want to delete this item? This action cannot be undone."
            submit={
              <Button variant="danger" onClick={() => setOpen(false)}>
                Delete
              </Button>
            }
            onClose={() => setOpen(false)}
          />
        )}
      </>
    );
  },
};

export const WarningConfirmation: Story = {
  render: () => {
    const [open, setOpen] = useState(true);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open Modal</button>
        {open && (
          <ConfirmationModalLayout
            icon={SvgAlertTriangle}
            title="Proceed with Caution"
            description="This operation will affect all users in the organization."
            submit={<Button onClick={() => setOpen(false)}>Confirm</Button>}
            onClose={() => setOpen(false)}
          />
        )}
      </>
    );
  },
};

export const WithChildren: Story = {
  render: () => {
    const [open, setOpen] = useState(true);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open Modal</button>
        {open && (
          <ConfirmationModalLayout
            icon={SvgCheckCircle}
            title="Review Changes"
            description="Please review the following changes before confirming."
            submit={<Button onClick={() => setOpen(false)}>Approve</Button>}
            onClose={() => setOpen(false)}
          >
            <ul style={{ listStyle: "disc", paddingLeft: 20 }}>
              <li>Updated email notification settings</li>
              <li>Changed default connector timeout to 30s</li>
              <li>Enabled automatic document syncing</li>
            </ul>
          </ConfirmationModalLayout>
        )}
      </>
    );
  },
};

export const HiddenCancel: Story = {
  render: () => {
    const [open, setOpen] = useState(true);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open Modal</button>
        {open && (
          <ConfirmationModalLayout
            icon={SvgCheckCircle}
            title="Welcome!"
            description="Thanks for signing up. Let's get you started."
            hideCancel
            submit={<Button onClick={() => setOpen(false)}>Get Started</Button>}
            onClose={() => setOpen(false)}
          />
        )}
      </>
    );
  },
};
