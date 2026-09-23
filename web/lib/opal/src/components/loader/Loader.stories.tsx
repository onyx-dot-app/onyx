import type { Meta, StoryObj } from "@storybook/react-vite";
import { OnyxLoader } from "@opal/components";

const meta: Meta<typeof OnyxLoader> = {
  title: "opal/components/Loader",
  component: OnyxLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

// OnyxLoader: the branded octagon/logo crossfade.

export const OnyxMark: Story = {
  render: () => <OnyxLoader />,
};

export const OnyxSizes: Story = {
  render: () => (
    <div className="flex items-end gap-6">
      <OnyxLoader size={24} />
      <OnyxLoader size={40} />
      <OnyxLoader size={64} />
    </div>
  ),
};

export const OnyxColors: Story = {
  render: () => (
    <div className="flex items-end gap-6">
      <OnyxLoader />
      <OnyxLoader color="text-04" />
      <OnyxLoader color="status-error-05" />
    </div>
  ),
};

// color="inherit" applies no class, so the mark takes the ambient text color.
export const Inherit: Story = {
  render: () => (
    <div className="flex items-center gap-6 text-status-error-05">
      <OnyxLoader color="inherit" />
    </div>
  ),
};
