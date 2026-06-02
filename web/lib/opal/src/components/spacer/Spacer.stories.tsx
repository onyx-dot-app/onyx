import type { Meta, StoryObj } from "@storybook/react";
import { Spacer } from "@opal/components/spacer/components";

const meta: Meta<typeof Spacer> = {
  title: "opal/components/Spacer",
  component: Spacer,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          background: "var(--background-neutral-01)",
          padding: "8px",
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            background: "var(--action-link-05)",
            borderRadius: 4,
          }}
        />
        <Story />
        <div
          style={{
            width: 40,
            height: 40,
            background: "var(--action-link-05)",
            borderRadius: 4,
          }}
        />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Spacer>;

export const VerticalRem: Story = {
  args: { orientation: "vertical", rem: 2 },
  decorators: [
    (Story) => (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          background: "var(--background-neutral-01)",
          padding: "8px",
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            background: "var(--action-link-05)",
            borderRadius: 4,
          }}
        />
        <Story />
        <div
          style={{
            width: 40,
            height: 40,
            background: "var(--action-link-05)",
            borderRadius: 4,
          }}
        />
      </div>
    ),
  ],
};

export const HorizontalRem: Story = {
  args: { orientation: "horizontal", rem: 2 },
};
