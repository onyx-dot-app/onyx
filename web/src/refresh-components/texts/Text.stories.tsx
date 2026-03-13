import type { Meta, StoryObj } from "@storybook/react";
import Text from "./Text";

const meta: Meta<typeof Text> = {
  title: "refresh-components/texts/Text",
  component: Text,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Text>;

export const Default: Story = {
  args: {
    children: "Hello, this is some default text.",
  },
};

export const Colors: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Text text01 mainUiBody>
        text01 — Primary text color
      </Text>
      <Text text02 mainUiBody>
        text02 — Secondary text color
      </Text>
      <Text text03 mainUiBody>
        text03 — Tertiary text color
      </Text>
      <Text text04 mainUiBody>
        text04 — Quaternary text color
      </Text>
      <Text text05 mainUiBody>
        text05 — Quinary text color
      </Text>
    </div>
  ),
};

export const Typography: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Text headingH2>Heading H2</Text>
      <Text mainContentBody>Main Content Body</Text>
      <Text mainUiBody>Main UI Body</Text>
      <Text secondaryBody>Secondary Body</Text>
    </div>
  ),
};

export const Emphasis: Story = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Text mainContentEmphasis>Main Content Emphasis</Text>
      <Text mainUiAction>Main UI Action</Text>
    </div>
  ),
};
