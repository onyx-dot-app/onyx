import type { Meta, StoryObj } from "@storybook/react";
import { PageLoader } from "@opal/layouts";
import { markdown } from "@opal/utils";

const meta: Meta<typeof PageLoader> = {
  title: "opal/layouts/PageLoader",
  component: PageLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof PageLoader>;

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
