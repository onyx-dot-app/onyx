import type { Meta, StoryObj } from "@storybook/react-vite";
import { MessageCard } from "@opal/components";
import { StickyBox } from "@opal/layouts/sticky-box/components";

const meta: Meta<typeof StickyBox> = {
  title: "Layouts/StickyBox",
  component: StickyBox,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj<typeof StickyBox>;

function Filler({ rows }: { rows: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="h-12 rounded-08 bg-background-neutral-01 flex items-center px-4"
        >
          Row {i + 1}
        </div>
      ))}
    </div>
  );
}

/** Scroll the panel: the card pins 8px from the top and casts a shadow. */
export const Top: Story = {
  render: () => (
    <div className="h-96 overflow-y-auto p-4 flex flex-col gap-4">
      <Filler rows={3} />
      <StickyBox stick="top" inset={2} shadow>
        <MessageCard
          variant="warning"
          title="Changes require a full re-index."
          description="Scroll to see the box pin and cast its shadow."
        />
      </StickyBox>
      <Filler rows={30} />
    </div>
  ),
};

/** Pinned to the bottom edge instead. */
export const Bottom: Story = {
  render: () => (
    <div className="h-96 overflow-y-auto p-4 flex flex-col gap-4">
      <Filler rows={30} />
      <StickyBox stick="bottom" inset={2} shadow>
        <MessageCard variant="info" title="Pinned to the bottom." />
      </StickyBox>
      <Filler rows={3} />
    </div>
  ),
};

/** `active` off: a plain block in the flow. */
export const Inactive: Story = {
  render: () => (
    <div className="h-96 overflow-y-auto p-4 flex flex-col gap-4">
      <Filler rows={3} />
      <StickyBox active={false} shadow>
        <MessageCard title="Nothing staged, so nothing pins." />
      </StickyBox>
      <Filler rows={30} />
    </div>
  ),
};
