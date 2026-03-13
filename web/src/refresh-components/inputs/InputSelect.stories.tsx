import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import InputSelect from "./InputSelect";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof InputSelect> = {
  title: "refresh-components/inputs/InputSelect",
  component: InputSelect,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ width: 320 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof InputSelect>;

export const Default: Story = {
  render: () => (
    <InputSelect defaultValue="option1">
      <InputSelect.Trigger placeholder="Select an option" />
      <InputSelect.Content>
        <InputSelect.Item value="option1">Option 1</InputSelect.Item>
        <InputSelect.Item value="option2">Option 2</InputSelect.Item>
        <InputSelect.Item value="option3">Option 3</InputSelect.Item>
      </InputSelect.Content>
    </InputSelect>
  ),
};

export const WithPlaceholder: Story = {
  render: () => (
    <InputSelect>
      <InputSelect.Trigger placeholder="Choose a fruit..." />
      <InputSelect.Content>
        <InputSelect.Item value="apple">Apple</InputSelect.Item>
        <InputSelect.Item value="banana">Banana</InputSelect.Item>
        <InputSelect.Item value="cherry">Cherry</InputSelect.Item>
      </InputSelect.Content>
    </InputSelect>
  ),
};

export const Controlled: Story = {
  render: function ControlledStory() {
    const [value, setValue] = React.useState("b");
    return (
      <InputSelect value={value} onValueChange={setValue}>
        <InputSelect.Trigger placeholder="Select..." />
        <InputSelect.Content>
          <InputSelect.Item value="a">Alpha</InputSelect.Item>
          <InputSelect.Item value="b">Bravo</InputSelect.Item>
          <InputSelect.Item value="c">Charlie</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
    );
  },
};

export const Disabled: Story = {
  render: () => (
    <InputSelect defaultValue="option1" disabled>
      <InputSelect.Trigger placeholder="Select an option" />
      <InputSelect.Content>
        <InputSelect.Item value="option1">Option 1</InputSelect.Item>
        <InputSelect.Item value="option2">Option 2</InputSelect.Item>
      </InputSelect.Content>
    </InputSelect>
  ),
};

export const ErrorState: Story = {
  render: () => (
    <InputSelect error>
      <InputSelect.Trigger placeholder="Required field" />
      <InputSelect.Content>
        <InputSelect.Item value="x">X</InputSelect.Item>
        <InputSelect.Item value="y">Y</InputSelect.Item>
      </InputSelect.Content>
    </InputSelect>
  ),
};

export const WithGroups: Story = {
  render: () => (
    <InputSelect defaultValue="gpt4o">
      <InputSelect.Trigger placeholder="Choose a model..." />
      <InputSelect.Content>
        <InputSelect.Group>
          <InputSelect.Label>OpenAI</InputSelect.Label>
          <InputSelect.Item value="gpt4o">GPT-4o</InputSelect.Item>
          <InputSelect.Item value="gpt4o-mini">GPT-4o Mini</InputSelect.Item>
        </InputSelect.Group>
        <InputSelect.Separator />
        <InputSelect.Group>
          <InputSelect.Label>Anthropic</InputSelect.Label>
          <InputSelect.Item value="opus">Claude Opus</InputSelect.Item>
          <InputSelect.Item value="sonnet">Claude Sonnet</InputSelect.Item>
        </InputSelect.Group>
      </InputSelect.Content>
    </InputSelect>
  ),
};

export const WithDescription: Story = {
  render: () => (
    <InputSelect>
      <InputSelect.Trigger placeholder="Select a plan..." />
      <InputSelect.Content>
        <InputSelect.Item value="free" description="Up to 5 users">
          Free
        </InputSelect.Item>
        <InputSelect.Item value="pro" description="Unlimited users">
          Pro
        </InputSelect.Item>
        <InputSelect.Item value="enterprise" description="Custom limits">
          Enterprise
        </InputSelect.Item>
      </InputSelect.Content>
    </InputSelect>
  ),
};
