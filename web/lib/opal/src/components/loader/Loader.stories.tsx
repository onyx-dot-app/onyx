import type { Meta, StoryObj } from "@storybook/react";
import { OnyxLoader, PageLoader } from "@opal/components";
import { markdown } from "@opal/utils";

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

export const FullPage: Story = {
  render: () => (
    <div className="h-96 w-full">
      <PageLoader />
    </div>
  ),
};

export const CustomLabel: Story = {
  render: () => (
    <div className="h-96 w-full">
      <PageLoader text="Fetching documents …" />
    </div>
  ),
};

export const MarkdownLabel: Story = {
  render: () => (
    <div className="h-96 w-full">
      <PageLoader text={markdown("**Indexing** your documents …")} />
    </div>
  ),
};
