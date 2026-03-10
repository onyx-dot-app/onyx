import type { Meta, StoryObj } from "@storybook/react";
import InputAvatar from "./InputAvatar";
import * as AvatarPrimitive from "@radix-ui/react-avatar";

const meta: Meta<typeof InputAvatar> = {
  title: "refresh-components/inputs/InputAvatar",
  component: InputAvatar,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
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
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputAvatar>;

export const WithImage: Story = {
  render: () => (
    <InputAvatar>
      <AvatarPrimitive.Image
        src="https://picsum.photos/80"
        alt="User avatar"
        className="h-full w-full object-cover"
      />
      <AvatarPrimitive.Fallback className="flex h-full w-full items-center justify-center bg-background-tint-02 text-text-03 text-sm font-medium">
        AB
      </AvatarPrimitive.Fallback>
    </InputAvatar>
  ),
};

export const WithFallback: Story = {
  render: () => (
    <InputAvatar>
      <AvatarPrimitive.Fallback className="flex h-full w-full items-center justify-center bg-background-tint-02 text-text-03 text-sm font-medium">
        JD
      </AvatarPrimitive.Fallback>
    </InputAvatar>
  ),
};

export const Empty: Story = {
  render: () => (
    <InputAvatar>
      <AvatarPrimitive.Fallback className="flex h-full w-full items-center justify-center bg-background-tint-02 text-text-04 text-xs">
        ?
      </AvatarPrimitive.Fallback>
    </InputAvatar>
  ),
};
