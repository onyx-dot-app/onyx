import type { Meta, StoryObj } from "@storybook/react";
import { OnyxLoader, IconLoader } from "@opal/components";
import { SvgSettings } from "@opal/icons";

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

// IconLoader: generic spinner that spins any icon.

export const DefaultSpinner: Story = {
  render: () => <IconLoader />,
};

export const CustomIcon: Story = {
  render: () => <IconLoader icon={SvgSettings} size={40} />,
};

export const IconColors: Story = {
  render: () => (
    <div className="flex items-end gap-6">
      <IconLoader size={32} />
      <IconLoader size={32} color="text-04" />
      <IconLoader size={32} color="status-success-05" />
    </div>
  ),
};
