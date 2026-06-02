import type { Meta, StoryObj } from "@storybook/react";
import InterruptHint from "@/app/craft/components/InterruptHint";

const meta: Meta<typeof InterruptHint> = {
  title: "Apps/Craft/Input Bar/Interrupt Hint",
  component: InterruptHint,
  tags: ["autodocs"],
  args: {
    armed: false,
    interrupting: false,
  },
};

export default meta;
type Story = StoryObj<typeof InterruptHint>;

/** At rest while streaming — teaches the double-Esc interrupt. */
export const Default: Story = {};

/** After the first Esc — the first keycap lights; a second Esc interrupts. */
export const Armed: Story = {
  args: {
    armed: true,
  },
};

/** Interrupt requested, awaiting the turn to terminate. */
export const Interrupting: Story = {
  args: {
    interrupting: true,
  },
};
