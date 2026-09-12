import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputSingleSelect } from "@opal/components";
import { SvgCloud, SvgCpu, SvgSparkle } from "@opal/icons";

const meta: Meta<typeof InputSingleSelect> = {
  title: "opal/components/InputSingleSelect",
  component: InputSingleSelect,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputSingleSelect>;

export const Default: Story = {
  render: () => (
    <div className="w-72">
      <InputSingleSelect defaultValue="fast">
        <InputSingleSelect.Trigger placeholder="Pick a tier" />
        <InputSingleSelect.Content>
          <InputSingleSelect.Item value="fast" icon={SvgSparkle}>
            Fast
          </InputSingleSelect.Item>
          <InputSingleSelect.Item
            value="balanced"
            icon={SvgCpu}
            description="Good default"
          >
            Balanced
          </InputSingleSelect.Item>
          <InputSingleSelect.Item value="thorough" icon={SvgCloud}>
            Thorough
          </InputSingleSelect.Item>
        </InputSingleSelect.Content>
      </InputSingleSelect>
    </div>
  ),
};

export const Controlled: Story = {
  render: () => {
    const [value, setValue] = useState<string | undefined>(undefined);
    return (
      <div className="w-72">
        <InputSingleSelect value={value} onValueChange={setValue}>
          <InputSingleSelect.Trigger placeholder="Select a region" />
          <InputSingleSelect.Content>
            <InputSingleSelect.Item value="us">
              United States
            </InputSingleSelect.Item>
            <InputSingleSelect.Item value="eu">
              European Union
            </InputSingleSelect.Item>
            <InputSingleSelect.Item value="apac">
              Asia Pacific
            </InputSingleSelect.Item>
          </InputSingleSelect.Content>
        </InputSingleSelect>
      </div>
    );
  },
};

export const Groups: Story = {
  render: () => (
    <div className="w-72">
      <InputSingleSelect>
        <InputSingleSelect.Trigger placeholder="Choose a model" />
        <InputSingleSelect.Content>
          <InputSingleSelect.Group>
            <InputSingleSelect.Label>OpenAI</InputSingleSelect.Label>
            <InputSingleSelect.Item value="gpt-mini">
              GPT-5 Mini
            </InputSingleSelect.Item>
            <InputSingleSelect.Item value="gpt">GPT-5</InputSingleSelect.Item>
          </InputSingleSelect.Group>
          <InputSingleSelect.Separator />
          <InputSingleSelect.Group>
            <InputSingleSelect.Label>Anthropic</InputSingleSelect.Label>
            <InputSingleSelect.Item value="haiku">
              Claude Haiku
            </InputSingleSelect.Item>
            <InputSingleSelect.Item value="opus">
              Claude Opus
            </InputSingleSelect.Item>
          </InputSingleSelect.Group>
        </InputSingleSelect.Content>
      </InputSingleSelect>
    </div>
  ),
};

export const Error: Story = {
  render: () => (
    <div className="w-72">
      <InputSingleSelect error>
        <InputSingleSelect.Trigger placeholder="Required field" />
        <InputSingleSelect.Content>
          <InputSingleSelect.Item value="x">Option</InputSingleSelect.Item>
        </InputSingleSelect.Content>
      </InputSingleSelect>
    </div>
  ),
};

export const Disabled: Story = {
  render: () => (
    <div className="w-72">
      <InputSingleSelect disabled defaultValue="x">
        <InputSingleSelect.Trigger />
        <InputSingleSelect.Content>
          <InputSingleSelect.Item value="x">
            Locked option
          </InputSingleSelect.Item>
        </InputSingleSelect.Content>
      </InputSingleSelect>
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
      <InputSingleSelect
        value={value}
        onValueChange={setValue}
        onOpenChange={(open) => {
          if (open) setQuery("");
        }}
      >
        <InputSingleSelect.Trigger placeholder="Select an agent" />
        <InputSingleSelect.Content>
          <InputSingleSelect.Search
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search agents..."
          />
          {filtered.map((name) => (
            <InputSingleSelect.Item key={name} value={name}>
              {name}
            </InputSingleSelect.Item>
          ))}
        </InputSingleSelect.Content>
      </InputSingleSelect>
    </div>
  );
}

export const Searchable: Story = {
  render: () => <SearchableHarness />,
};
