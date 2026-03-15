import type { Meta, StoryObj } from "@storybook/react";
import PreviewImage from "./PreviewImage";

const meta: Meta<typeof PreviewImage> = {
  title: "refresh-components/PreviewImage",
  component: PreviewImage,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof PreviewImage>;

export const Default: Story = {
  args: {
    src: "https://placehold.co/400x300/EEE/31343C?text=Preview+Image",
    alt: "Sample preview image",
  },
};

export const WithCustomClass: Story = {
  args: {
    src: "https://placehold.co/200x200/EEE/31343C?text=Square",
    alt: "Square preview",
    className: "w-[200px] h-[200px] rounded-12",
  },
};

export const Landscape: Story = {
  args: {
    src: "https://placehold.co/600x200/EEE/31343C?text=Landscape",
    alt: "Landscape preview",
    className: "max-w-[400px]",
  },
};
