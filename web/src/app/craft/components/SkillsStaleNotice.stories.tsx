import type { Meta, StoryObj } from "@storybook/react";
import SkillsStaleNotice from "@/app/craft/components/SkillsStaleNotice";

const meta: Meta<typeof SkillsStaleNotice> = {
  title: "Apps/Craft/Session/Skills Stale Notice",
  component: SkillsStaleNotice,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px] max-w-full">
        <Story />
      </div>
    ),
  ],
  args: {
    sessionId: "11111111-1111-1111-1111-111111111111",
    turnActive: false,
  },
};

export default meta;
type Story = StoryObj<typeof SkillsStaleNotice>;

/** The session is idle, so its updated skills can be loaded immediately. */
export const ReadyToReload: Story = {};

/** Reload waits until the active turn finishes to avoid interrupting it. */
export const ActiveTurn: Story = {
  args: {
    turnActive: true,
  },
};
