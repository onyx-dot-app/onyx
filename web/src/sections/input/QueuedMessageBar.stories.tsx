import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import QueuedMessageBar from "@/sections/input/QueuedMessageBar";
import { QueuedMessage } from "@/app/app/interfaces";

const SAMPLE_MESSAGES: QueuedMessage[] = [
  { id: 1, text: "Add a dark mode toggle to the settings page" },
  { id: 2, text: "Then write tests for it" },
  {
    id: 3,
    text: "And update the changelog with a short summary of the change",
  },
];

// Pills shown above the chat input for messages queued while a response
// streams. Shared by the main chat and Craft input bars.
const meta: Meta<typeof QueuedMessageBar> = {
  title: "Sections/Input/Queued Message Bar",
  component: QueuedMessageBar,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px]">
        <Story />
      </div>
    ),
  ],
  args: {
    messages: SAMPLE_MESSAGES,
    highlightedIndex: null,
    awaitingPreferredSelection: false,
    onDiscard: (index: number) => console.log("onDiscard", index),
    onHighlight: (index: number | null) => console.log("onHighlight", index),
  },
};

export default meta;
type Story = StoryObj<typeof QueuedMessageBar>;

export const Default: Story = {};

/** A highlighted pill reveals the "↵ edit · ⌫ remove" keyboard hint. */
export const Highlighted: Story = {
  args: {
    highlightedIndex: 1,
  },
};

/**
 * When the chat is waiting for the user to pick a response, the head of the
 * queue shows a "Select a response to continue" label instead.
 */
export const AwaitingPreferredSelection: Story = {
  args: {
    awaitingPreferredSelection: true,
  },
};

export const SingleMessage: Story = {
  args: {
    messages: [SAMPLE_MESSAGES[0]!],
  },
};

/**
 * Interactive: click a pill to highlight it, click the trash icon to discard.
 * State is owned here to mirror how the input bars wire up the bar.
 */
function InteractiveDemo() {
  const [messages, setMessages] = useState<QueuedMessage[]>(SAMPLE_MESSAGES);
  const [highlightedIndex, setHighlightedIndex] = useState<number | null>(null);

  return (
    <QueuedMessageBar
      messages={messages}
      highlightedIndex={highlightedIndex}
      awaitingPreferredSelection={false}
      onHighlight={setHighlightedIndex}
      onDiscard={(index) => {
        setMessages((prev) => prev.filter((_, i) => i !== index));
        setHighlightedIndex(null);
      }}
    />
  );
}

export const Interactive: Story = {
  render: () => <InteractiveDemo />,
};
