import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "./Collapsible";

const meta: Meta<typeof Collapsible> = {
  title: "refresh-components/Collapsible",
  component: Collapsible,
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;
type Story = StoryObj<typeof Collapsible>;

export const Default: Story = {
  render: () => (
    <Collapsible defaultOpen={false}>
      <CollapsibleTrigger asChild>
        <button className="p-2 bg-background-tint-03 rounded-08 font-main-ui-action w-full text-left">
          Click to toggle
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="p-4 border border-border-01 rounded-08 mt-2">
          This content can be expanded and collapsed with a smooth animation.
        </div>
      </CollapsibleContent>
    </Collapsible>
  ),
};

export const DefaultOpen: Story = {
  render: () => (
    <Collapsible defaultOpen>
      <CollapsibleTrigger asChild>
        <button className="p-2 bg-background-tint-03 rounded-08 font-main-ui-action w-full text-left">
          Already open — click to close
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="p-4 border border-border-01 rounded-08 mt-2">
          This section starts open by default.
        </div>
      </CollapsibleContent>
    </Collapsible>
  ),
};

function ControlledDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <div style={{ width: 320 }}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button className="p-2 bg-background-tint-03 rounded-08 font-main-ui-action w-full text-left">
            {open ? "Close" : "Open"} (controlled)
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="p-4 border border-border-01 rounded-08 mt-2">
            Controlled collapsible content. Current state:{" "}
            {open ? "open" : "closed"}.
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

export const Controlled: Story = {
  render: () => <ControlledDemo />,
};

export const MultipleCollapsibles: Story = {
  render: () => (
    <div className="flex flex-col gap-2" style={{ width: 320 }}>
      {["Section A", "Section B", "Section C"].map((title) => (
        <Collapsible key={title}>
          <CollapsibleTrigger asChild>
            <button className="p-2 bg-background-tint-03 rounded-08 font-main-ui-action w-full text-left">
              {title}
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-4 border border-border-01 rounded-08 mt-1">
              Content for {title}
            </div>
          </CollapsibleContent>
        </Collapsible>
      ))}
    </div>
  ),
};
