import type { Meta, StoryObj } from "@storybook/react";
import LivingMapModal from "@/app/craft/onboarding/components/LivingMapModal";
import { LIVING_MAP_STAGES } from "@/app/craft/onboarding/components/LivingMapDiagram";
import WelcomePageMock from "@/app/craft/onboarding/explorations/WelcomePageMock";

// The Living Map, filmed by a camera — one fixed world (prompt → Craft's
// machine reading your sources → outputs, schedule and team at the edges);
// each stage is a camera framing. Next pulls back and refocuses: sharp
// subjects for the current stage, everything else soft at the edges. The
// final CTA dives back into the prompt. Every node is clickable.
const meta: Meta<typeof LivingMapModal> = {
  title: "Apps/Craft/Onboarding Explorations/Living Map",
  component: LivingMapModal,
  parameters: { layout: "fullscreen" },
  args: { open: true },
  argTypes: {
    initialStage: {
      control: "select",
      options: LIVING_MAP_STAGES.map((stage) => stage.id),
    },
    onComplete: { action: "complete" },
    onDismiss: { action: "dismiss" },
  },
  render: (args) => (
    <WelcomePageMock dimmed>
      <LivingMapModal {...args} />
    </WelcomePageMock>
  ),
};

export default meta;
type Story = StoryObj<typeof LivingMapModal>;

/** The modal over the craft welcome page, exactly where it would ship. */
export const InContext: Story = {};

/** Stage 2 — the camera pulls back to Craft's machine and your sources. */
export const StageMachine: Story = {
  args: { initialStage: "machine" },
};

/** Stage 3 — wider still: outputs flow out, the schedule re-runs the loop. */
export const StageOutput: Story = {
  args: { initialStage: "output" },
};

/** Stage 4 — the full constellation, everything sharp, CTA to dive back in. */
export const StageConstellation: Story = {
  args: { initialStage: "constellation" },
};
