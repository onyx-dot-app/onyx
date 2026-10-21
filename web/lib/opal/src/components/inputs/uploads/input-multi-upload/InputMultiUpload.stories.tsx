import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import InputMultiUpload from "@opal/components/inputs/uploads/input-multi-upload/components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputMultiUpload> = {
  title: "opal/components/InputMultiUpload",
  component: InputMultiUpload,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 400 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputMultiUpload>;

export const Default: Story = {
  render: function DefaultStory() {
    const [files, setFiles] = React.useState<File[]>([]);
    return <InputMultiUpload value={files} onFilesChange={setFiles} />;
  },
};

export const Error: Story = {
  render: function ErrorStory() {
    const [files, setFiles] = React.useState<File[]>([]);
    return (
      <InputMultiUpload
        variant="error"
        value={files}
        onFilesChange={setFiles}
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputMultiUpload variant="disabled" onFilesChange={() => {}} />
  ),
};
