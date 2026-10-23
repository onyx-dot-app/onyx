import type { Meta, StoryObj } from "@storybook/react-vite";
import React from "react";
import InputSingleUpload from "@opal/components/inputs/uploads/input-single-upload/components";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputSingleUpload> = {
  title: "opal/components/InputSingleUpload",
  component: InputSingleUpload,
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
type Story = StoryObj<typeof InputSingleUpload>;

export const Default: Story = {
  render: function DefaultStory() {
    const [, setValue] = React.useState("");
    return (
      <InputSingleUpload
        placeholder="Paste or attach a file..."
        setValue={setValue}
      />
    );
  },
};

export const WithAcceptFilter: Story = {
  render: function AcceptFilterStory() {
    const [, setValue] = React.useState("");
    return (
      <InputSingleUpload
        placeholder="JSON files only..."
        setValue={setValue}
        accept="application/json,.json"
      />
    );
  },
};

export const WithMaxSize: Story = {
  render: function MaxSizeStory() {
    const [, setValue] = React.useState("");
    return (
      <InputSingleUpload
        placeholder="Max 100KB..."
        setValue={setValue}
        maxSizeKb={100}
        onFileSizeExceeded={({ file, maxSizeKb }) =>
          alert(`${file.name} exceeds ${maxSizeKb}KB limit`)
        }
      />
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputSingleUpload
      placeholder="Cannot upload"
      setValue={() => {}}
      variant="disabled"
    />
  ),
};

export const ErrorState: Story = {
  render: function ErrorStory() {
    const [, setValue] = React.useState("");
    return (
      <InputSingleUpload
        placeholder="Required file..."
        setValue={setValue}
        variant="error"
      />
    );
  },
};

export const FileMode: Story = {
  render: function FileModeStory() {
    const [file, setFile] = React.useState<File | null>(null);
    return (
      <InputSingleUpload
        mode="file"
        accept=".pfx"
        placeholder="Attach a .pfx certificate"
        value={file}
        onFileChange={setFile}
      />
    );
  },
};
