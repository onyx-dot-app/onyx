import type { Meta, StoryObj } from "@storybook/react";
import FrostedDiv from "./FrostedDiv";

const meta: Meta<typeof FrostedDiv> = {
  title: "refresh-components/FrostedDiv",
  component: FrostedDiv,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => (
      <div
        className="p-12"
        style={{
          background:
            "linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)",
        }}
      >
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof FrostedDiv>;

export const Default: Story = {
  args: {
    className: "p-4",
    children: (
      <span className="text-text-04 font-main-ui-action">
        Frosted glass content
      </span>
    ),
  },
};

export const CustomBlur: Story = {
  args: {
    blur: "30px",
    backdropBlur: "10px",
    className: "p-6",
    children: (
      <span className="text-text-04 font-main-ui-action">
        Heavy blur effect
      </span>
    ),
  },
};

export const CustomBorderRadius: Story = {
  args: {
    borderRadius: "0.5rem",
    className: "p-4",
    children: (
      <span className="text-text-04 font-main-ui-action">Rounded corners</span>
    ),
  },
};
