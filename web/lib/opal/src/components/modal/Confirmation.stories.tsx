import type { Meta, StoryObj } from "@storybook/react";
import {
  Button,
  ConfirmationModalLayout,
  useCreateModal,
} from "@opal/components";
import { SvgTrash } from "@opal/icons";

const meta: Meta<typeof ConfirmationModalLayout> = {
  title: "opal/components/ConfirmationModalLayout",
  component: ConfirmationModalLayout,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof ConfirmationModalLayout>;

export const Default: Story = {
  render: () => {
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
  },
};

export const NoCancel: Story = {
  render: () => {
    const modal = useCreateModal();
    return (
      <>
        <Button onClick={() => modal.toggle(true)}>Show notice</Button>
        <modal.Provider>
          <ConfirmationModalLayout
            icon={SvgTrash}
            title="Session expired"
            hideCancel
            submit={<Button onClick={() => modal.toggle(false)}>OK</Button>}
          >
            Sign in again to continue.
          </ConfirmationModalLayout>
        </modal.Provider>
      </>
    );
  },
};
