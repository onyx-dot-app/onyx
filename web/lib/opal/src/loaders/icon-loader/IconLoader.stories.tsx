import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "@opal/components";
import { IconLoader } from "@opal/loaders";

const meta: Meta<typeof IconLoader> = {
  title: "opal/loaders/IconLoader",
  component: IconLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof IconLoader>;

export const Default: Story = {
  render: () => <IconLoader />,
};

export const Sizes: Story = {
  render: () => (
    <div className="flex items-center gap-4">
      <IconLoader />
      <IconLoader size={24} />
      <IconLoader size={32} className="text-text-03" />
    </div>
  ),
};

// Passed as an icon, the host sets the size.
export const AsButtonIcon: Story = {
  render: () => (
    <Button icon={IconLoader} prominence="secondary">
      Saving
    </Button>
  ),
};
