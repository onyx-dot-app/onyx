import type { Meta, StoryObj } from "@storybook/react";
import SkillBadge from "@/app/craft/components/tool-cards/SkillBadge";

const meta: Meta<typeof SkillBadge> = {
  title: "Apps/Craft/Tool Cards/Skill Badge",
  component: SkillBadge,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof SkillBadge>;

export const Default: Story = {
  args: { name: "code-review" },
};

export const LongName: Story = {
  args: { name: "playwright-test-author" },
};

export const Variants: Story = {
  render: () => (
    <div className="flex flex-col gap-2 items-start">
      <SkillBadge name="code-review" />
      <SkillBadge name="security-review" />
      <SkillBadge name="onyx-cli" />
      <SkillBadge name="pdf" />
      <SkillBadge name="playwright" />
    </div>
  ),
};
