import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputFile from "./InputFile";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputFile> = {
  title: "refresh-components/inputs/InputFile",
  component: InputFile,
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
type Story = StoryObj<typeof InputFile>;

export const Default: Story = {
  render: function DefaultStory() {
    const [, setValue] = React.useState("");
    return (
      <InputFile placeholder="Paste or attach a file..." setValue={setValue} />
    );
  },
};

export const WithAcceptFilter: Story = {
  render: function AcceptFilterStory() {
    const [, setValue] = React.useState("");
    return (
      <InputFile
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
      <InputFile
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
    <InputFile placeholder="Cannot upload" setValue={() => {}} disabled />
  ),
};

export const ErrorState: Story = {
  render: function ErrorStory() {
    const [, setValue] = React.useState("");
    return (
      <InputFile placeholder="Required file..." setValue={setValue} error />
    );
  },
};
