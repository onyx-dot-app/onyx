import type { Meta, StoryObj } from "@storybook/react";
import LivingMapModal from "@/app/craft/onboarding/components/LivingMapModal";
import { LIVING_MAP_STAGES } from "@/app/craft/onboarding/components/LivingMapDiagram";
import WelcomePageMock from "@/app/craft/onboarding/explorations/WelcomePageMock";

// The Living Map — the whole Craft ecosystem on one map, under a single
// "Meet Craft" title. The core loop (prompt → Craft in its workspace reading
// your sources → output) is taught first; then the ecosystem attaches piece
// by piece — apps, skills, scheduled tasks, and team sharing — ending on the
// complete constellation. Every node is clickable and jumps to its stage.
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

/** Stage 2 — apps attach: Craft acts where you work, with your approval. */
export const StageApps: Story = {
  args: { initialStage: "apps" },
};

/** Stage 3 — skills join the map: your team's playbooks for Craft. */
export const StageSkills: Story = {
  args: { initialStage: "skills" },
};

/** Stage 4 — a scheduled task attaches and re-runs the prompt on a timer. */
export const StageSchedule: Story = {
  args: { initialStage: "schedule" },
};

/** Stage 5 — finished work stays private until one link opens it org-wide. */
export const StageShare: Story = {
  args: { initialStage: "share" },
};

/** Stage 6 — the complete constellation: the full map, recapped. */
export const StageWorkshop: Story = {
  args: { initialStage: "workshop" },
};
