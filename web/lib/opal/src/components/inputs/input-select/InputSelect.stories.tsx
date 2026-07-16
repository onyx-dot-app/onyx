import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { InputSelect } from "@opal/components";
import { SvgCloud, SvgCpu, SvgSparkle } from "@opal/icons";

const meta: Meta<typeof InputSelect> = {
  title: "opal/components/InputSelect",
  component: InputSelect,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputSelect>;

export const Default: Story = {
  render: () => (
    <div className="w-72">
      <InputSelect defaultValue="fast">
        <InputSelect.Trigger placeholder="Pick a tier" />
        <InputSelect.Content>
          <InputSelect.Item value="fast" icon={SvgSparkle}>
            Fast
          </InputSelect.Item>
          <InputSelect.Item
            value="balanced"
            icon={SvgCpu}
            description="Good default"
          >
            Balanced
          </InputSelect.Item>
          <InputSelect.Item value="thorough" icon={SvgCloud}>
            Thorough
          </InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
    </div>
  ),
};

export const Controlled: Story = {
  render: () => {
    const [value, setValue] = useState<string | undefined>(undefined);
    return (
      <div className="w-72">
        <InputSelect value={value} onValueChange={setValue}>
          <InputSelect.Trigger placeholder="Select a region" />
          <InputSelect.Content>
            <InputSelect.Item value="us">United States</InputSelect.Item>
            <InputSelect.Item value="eu">European Union</InputSelect.Item>
            <InputSelect.Item value="apac">Asia Pacific</InputSelect.Item>
          </InputSelect.Content>
        </InputSelect>
      </div>
    );
  },
};

export const Groups: Story = {
  render: () => (
    <div className="w-72">
      <InputSelect>
        <InputSelect.Trigger placeholder="Choose a model" />
        <InputSelect.Content>
          <InputSelect.Group>
            <InputSelect.Label>OpenAI</InputSelect.Label>
            <InputSelect.Item value="gpt-mini">GPT-5 Mini</InputSelect.Item>
            <InputSelect.Item value="gpt">GPT-5</InputSelect.Item>
          </InputSelect.Group>
          <InputSelect.Separator />
          <InputSelect.Group>
            <InputSelect.Label>Anthropic</InputSelect.Label>
            <InputSelect.Item value="haiku">Claude Haiku</InputSelect.Item>
            <InputSelect.Item value="opus">Claude Opus</InputSelect.Item>
          </InputSelect.Group>
        </InputSelect.Content>
      </InputSelect>
    </div>
  ),
};

export const Error: Story = {
  render: () => (
    <div className="w-72">
      <InputSelect error>
        <InputSelect.Trigger placeholder="Required field" />
        <InputSelect.Content>
          <InputSelect.Item value="x">Option</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
    </div>
  ),
};

export const Disabled: Story = {
  render: () => (
    <div className="w-72">
      <InputSelect disabled defaultValue="x">
        <InputSelect.Trigger />
        <InputSelect.Content>
          <InputSelect.Item value="x">Locked option</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
    </div>
  ),
};

const AGENTS = [
  "General Assistant",
  "Search Copilot",
  "Sales Researcher",
  "Support Triage",
  "Code Reviewer",
  "Data Analyst",
  "Meeting Notetaker",
  "Onboarding Guide",
];

function SearchableHarness() {
  const [value, setValue] = useState<string | undefined>(undefined);
  const [query, setQuery] = useState("");
  const filtered = AGENTS.filter((name) =>
    name.toLowerCase().includes(query.toLowerCase())
  );
  return (
    <div className="w-72">
      <InputSelect
        value={value}
        onValueChange={setValue}
        onOpenChange={(open) => {
          if (open) setQuery("");
        }}
      >
        <InputSelect.Trigger placeholder="Select an agent" />
        <InputSelect.Content>
          <InputSelect.Search
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search agents..."
          />
          {filtered.map((name) => (
            <InputSelect.Item key={name} value={name}>
              {name}
            </InputSelect.Item>
          ))}
        </InputSelect.Content>
      </InputSelect>
    </div>
  );
}

export const Searchable: Story = {
  render: () => <SearchableHarness />,
};
