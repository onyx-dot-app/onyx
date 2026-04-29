import type { Meta, StoryObj } from "@storybook/react";
import { MessageCard, Button } from "@opal/components";

const meta: Meta<typeof MessageCard> = {
  title: "opal/components/MessageCard",
  component: MessageCard,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof MessageCard>;

export const Default: Story = {
  render: () => (
    <div className="w-[32rem]">
      <MessageCard title="Note" description="This is a default message card." />
    </div>
  ),
};

export const Info: Story = {
  render: () => (
    <div className="w-[32rem]">
      <MessageCard
        variant="info"
        title="Heads up"
        description="Changes apply to newly indexed documents only."
      />
    </div>
  ),
};

export const Success: Story = {
  render: () => (
    <div className="w-[32rem]">
      <MessageCard
        variant="success"
        title="All set"
        description="Your embedding model has been updated successfully."
      />
    </div>
  ),
};

export const Warning: Story = {
  render: () => (
    <div className="w-[32rem]">
      <MessageCard
        variant="warning"
        title="Re-indexing required"
        description="Toggle this setting to re-index all documents."
      />
    </div>
  ),
};

export const Error: Story = {
  render: () => (
    <div className="w-[32rem]">
      <MessageCard
        variant="error"
        title="Connection failed"
        description="Unable to reach the embedding model server."
      />
    </div>
  ),
};

export const WithBottomChildren: Story = {
  render: () => (
    <div className="w-[32rem]">
      <MessageCard
        variant="warning"
        title="Action required"
        description="Your documents need to be re-indexed after this change."
        bottomChildren={
          <div className="flex justify-end pt-2">
            <Button prominence="secondary" size="sm">
              Re-index Now
            </Button>
          </div>
        }
      />
    </div>
  ),
};

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-[32rem]">
      {(["default", "info", "success", "warning", "error"] as const).map(
        (variant) => (
          <MessageCard
            key={variant}
            variant={variant}
            title={`${
              variant.charAt(0).toUpperCase() + variant.slice(1)
            } variant`}
            description={`This is a ${variant} message card.`}
          />
        )
      )}
    </div>
  ),
};
