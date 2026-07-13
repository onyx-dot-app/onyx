import type { Meta, StoryObj } from "@storybook/react";
import { OnyxLoader } from "@opal/components";

const meta: Meta<typeof OnyxLoader> = {
  title: "opal/components/Loader",
  component: OnyxLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof OnyxLoader>;

export const Mark: Story = {
  render: () => <OnyxLoader />,
};

export const Sizes: Story = {
  render: () => (
    <div className="flex items-end gap-6">
      <OnyxLoader size={24} />
      <OnyxLoader size={40} />
      <OnyxLoader size={64} />
    </div>
  ),
};
