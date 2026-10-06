import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "@opal/components";
import { AttachmentItem } from "@opal/layouts";
import { SvgFileText, SvgUsers, SvgX } from "@opal/icons";

const meta: Meta<typeof AttachmentItem> = {
  title: "opal/layouts/AttachmentItem",
  component: AttachmentItem,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof AttachmentItem>;

export const Default: Story = {
  render: () => (
    <div className="w-96">
      <AttachmentItem
        icon={SvgFileText}
        title="Quarterly report.pdf"
        description="PDF"
      />
    </div>
  ),
};

export const Prominence: Story = {
  render: () => (
    <div className="flex w-96 flex-col gap-2">
      {(["primary", "secondary", "tertiary"] as const).map((prominence) => (
        <AttachmentItem
          key={prominence}
          prominence={prominence}
          icon={SvgUsers}
          title="Engineering"
          description={prominence}
        />
      ))}
    </div>
  ),
};

export const WithAction: Story = {
  render: () => (
    <div className="w-96">
      <AttachmentItem
        prominence="secondary"
        icon={SvgUsers}
        title="Engineering"
        description="12 members"
        rightChildren={
          <Button
            icon={SvgX}
            size="sm"
            prominence="internal"
            tooltip="Remove"
          />
        }
      />
    </div>
  ),
};
