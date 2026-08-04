import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  SandboxStatusIndicatorView,
  type SandboxDisplayStatus,
} from "@/app/craft/components/SandboxStatusIndicator";

const SANDBOX_STATUSES = [
  "loading",
  "provisioning",
  "ready",
  "running",
  "sleeping",
  "restoring",
  "terminated",
  "failed",
] as const satisfies readonly SandboxDisplayStatus[];

const meta: Meta<typeof SandboxStatusIndicatorView> = {
  title: "Apps/Craft/Session/Sandbox Status Indicator",
  component: SandboxStatusIndicatorView,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
  args: {
    status: "running",
  },
  argTypes: {
    status: {
      control: "select",
      options: SANDBOX_STATUSES,
    },
  },
};

export default meta;
type Story = StoryObj<typeof SandboxStatusIndicatorView>;

/** Inspect any display state using the status control. */
export const Playground: Story = {};

/** Every backend, client-runtime, and pre-provisioning display state. */
export const AllStates: Story = {
  render: () => (
    <div className="flex flex-wrap items-center justify-center gap-3 max-w-[640px]">
      {SANDBOX_STATUSES.map((status) => (
        <SandboxStatusIndicatorView key={status} status={status} />
      ))}
    </div>
  ),
};
