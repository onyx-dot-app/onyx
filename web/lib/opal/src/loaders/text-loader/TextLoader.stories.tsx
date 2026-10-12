import type { Meta, StoryObj } from "@storybook/react-vite";
import { TextLoader } from "@opal/loaders";

const meta: Meta<typeof TextLoader> = {
  title: "opal/loaders/TextLoader",
  component: TextLoader,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof TextLoader>;

export const Short: Story = {
  render: () => <TextLoader>Thinking…</TextLoader>,
};

// The wave scales with the length: every text gets a 2s crossing.
export const Lengths: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <TextLoader>Thinking…</TextLoader>
      <TextLoader>Searching the knowledge base…</TextLoader>
      <TextLoader>
        Reading 14 documents from Confluence, Google Drive and Slack…
      </TextLoader>
    </div>
  ),
};

// Wrapped text: the wave runs along each line in reading order.
export const Wrapping: Story = {
  render: () => (
    <div className="w-60">
      <TextLoader>
        Comparing the quarterly revenue figures across every regional report and
        reconciling the totals against the finance team's summary…
      </TextLoader>
    </div>
  ),
};

export const RightToLeft: Story = {
  render: () => (
    <div dir="rtl">
      <TextLoader>جارٍ التفكير…</TextLoader>
    </div>
  ),
};
