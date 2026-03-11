import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputImage from "./InputImage";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputImage> = {
  title: "refresh-components/inputs/InputImage",
  component: InputImage,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div
          style={{
            width: 320,
            display: "flex",
            justifyContent: "center",
            padding: 24,
          }}
        >
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputImage>;

export const Empty: Story = {
  args: {
    onDrop: () => {},
  },
};

export const WithImage: Story = {
  args: {
    src: "https://picsum.photos/200",
    alt: "Sample image",
    onEdit: () => {},
    onRemove: () => {},
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
    onDrop: () => {},
  },
};

export const DisabledWithImage: Story = {
  args: {
    src: "https://picsum.photos/200",
    alt: "Cannot edit",
    disabled: true,
  },
};

export const CustomSize: Story = {
  args: {
    size: 80,
    onDrop: () => {},
  },
};

export const LargeSize: Story = {
  args: {
    src: "https://picsum.photos/300",
    alt: "Large avatar",
    size: 160,
    onEdit: () => {},
    onRemove: () => {},
  },
};

export const NoEditOverlay: Story = {
  args: {
    src: "https://picsum.photos/200",
    alt: "No overlay",
    showEditOverlay: false,
    onEdit: () => {},
  },
};
