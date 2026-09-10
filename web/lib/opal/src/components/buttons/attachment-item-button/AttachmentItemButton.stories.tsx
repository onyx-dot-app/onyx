import type { Meta, StoryObj } from "@storybook/react-vite";
import { AttachmentItemButton, Button, Text } from "@opal/components";
import SvgFileText from "@opal/icons/file-text";
import SvgKey from "@opal/icons/key";
import SvgTrash from "@opal/icons/trash";
import SvgExternalLink from "@opal/icons/external-link";

const meta: Meta<typeof AttachmentItemButton> = {
  title: "opal/components/AttachmentItemButton",
  component: AttachmentItemButton,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof AttachmentItemButton>;

export const Default: Story = {
  render: () => (
    <div className="w-[32rem]">
      <AttachmentItemButton
        icon={SvgFileText}
        title="Research Doc"
        description="PDF"
      />
    </div>
  ),
};

export const States: Story = {
  render: () => (
    <div className="flex w-[32rem] flex-col gap-1">
      <AttachmentItemButton
        icon={SvgFileText}
        title="Empty"
        description="At rest"
      />
      <AttachmentItemButton
        icon={SvgFileText}
        title="Selected"
        description="Tile swaps to a checkbox"
        state="selected"
      />
      <AttachmentItemButton
        icon={SvgFileText}
        title="Disabled"
        description="Suppressed palette and clicks"
        disabled
      />
    </div>
  ),
};

/**
 * `select-heavy` rests transparent (list rows in a modal); `select-tinted`
 * rests on `background-tint-01` (rows on a plain page surface). Hover and
 * selected palettes come from `Interactive.Stateful` in both.
 */
export const SelectVariants: Story = {
  render: () => (
    <div className="flex w-[32rem] flex-col gap-1">
      <AttachmentItemButton
        icon={SvgFileText}
        title="select-heavy"
        description="Transparent at rest"
      />
      <AttachmentItemButton
        selectVariant="select-tinted"
        icon={SvgFileText}
        title="select-tinted"
        description="Tinted at rest"
      />
    </div>
  ),
};

export const Image: Story = {
  render: () => (
    <div className="w-[32rem]">
      <AttachmentItemButton
        imageSrc="https://picsum.photos/seed/opal/72"
        imageAlt="Random placeholder"
        title="Cover Image"
        description="PNG"
      />
    </div>
  ),
};

/**
 * The center slot expands between the title group and the action slot; the
 * action slot keeps its minimum width even when it has no children, so rows
 * with and without actions stay aligned.
 */
export const Slots: Story = {
  render: () => (
    <div className="flex w-[40rem] flex-col gap-1">
      <AttachmentItemButton
        icon={SvgFileText}
        title="With every slot"
        description="PDF"
        centerChildren={
          <div className="flex flex-row justify-end">
            <Text font="secondary-body" color="text-03">
              2 days ago
            </Text>
          </div>
        }
        rightChildren={
          <>
            <Button icon={SvgExternalLink} prominence="tertiary" size="sm" />
            <Button icon={SvgTrash} prominence="tertiary" size="sm" />
          </>
        }
      />
      <AttachmentItemButton
        icon={SvgFileText}
        title="No actions"
        description="The empty action slot still reserves its width"
      />
    </div>
  ),
};

export const Presentational: Story = {
  render: () => (
    <div className="w-[32rem]">
      <AttachmentItemButton
        presentational
        selectVariant="select-tinted"
        icon={SvgKey}
        title="Production key"
        description="sk-...4f2a"
        rightChildren={
          <Button icon={SvgTrash} prominence="tertiary" size="sm" />
        }
      />
    </div>
  ),
};

export const Editable: Story = {
  render: () => (
    <div className="w-[32rem]">
      <AttachmentItemButton
        presentational
        icon={SvgFileText}
        title="Rename me"
        description="Inline title editing via Content"
        editable
        onTitleChange={(next) => console.log("renamed to", next)}
      />
    </div>
  ),
};
