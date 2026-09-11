import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputMultiSelect, type TagItem } from "@opal/components";
import { SvgTag } from "@opal/icons";

const meta: Meta<typeof InputMultiSelect> = {
  title: "opal/components/InputMultiSelect",
  component: InputMultiSelect,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputMultiSelect>;

function ControlledInputMultiSelect(
  props: Partial<React.ComponentProps<typeof InputMultiSelect>>
) {
  const [tags, setTags] = useState<TagItem[]>([
    { id: "1", label: "Tag" },
    { id: "2", label: "2" },
  ]);
  const [value, setValue] = useState("");

  return (
    <div className="w-80">
      <InputMultiSelect
        tags={tags}
        onRemoveTag={(id) => setTags((prev) => prev.filter((t) => t.id !== id))}
        onAdd={(label) => {
          setTags((prev) => [...prev, { id: crypto.randomUUID(), label }]);
          setValue("");
        }}
        value={value}
        onChange={setValue}
        placeholder="Add a tag…"
        {...props}
      />
    </div>
  );
}

export const Default: Story = {
  render: () => <ControlledInputMultiSelect />,
};

export const WithIcon: Story = {
  render: () => <ControlledInputMultiSelect icon={SvgTag} />,
};

export const WithClear: Story = {
  render: () => <ControlledInputMultiSelect onClear={() => {}} />,
};

export const WithError: Story = {
  render: () => {
    const tags: TagItem[] = [
      { id: "1", label: "valid" },
      { id: "2", label: "not-an-email", error: true },
    ];
    return (
      <div className="w-80">
        <InputMultiSelect
          tags={tags}
          onRemoveTag={() => {}}
          onAdd={() => {}}
          value=""
          onChange={() => {}}
          placeholder="Add an email…"
        />
      </div>
    );
  },
};

export const Subtle: Story = {
  render: () => <ControlledInputMultiSelect variant="internal" />,
};

export const Disabled: Story = {
  render: () => <ControlledInputMultiSelect disabled />,
};

const GROUP_OPTIONS = [
  { value: "1", label: "Engineering", description: "14 members" },
  { value: "2", label: "Design", description: "5 members" },
  { value: "3", label: "Sales", description: "9 members" },
];

function ControlledWithOptions({ mode }: { mode?: "closed" | "open" }) {
  const [tags, setTags] = useState<TagItem[]>([]);
  const [text, setText] = useState("");
  return (
    <div className="w-96">
      <InputMultiSelect
        tags={tags}
        value={text}
        onChange={setText}
        mode={mode}
        options={GROUP_OPTIONS}
        placeholder="Pick groups…"
        createPrefix="Add"
        onSelectOption={(option) =>
          setTags((prev) => [
            ...prev,
            { id: option.value, label: option.label },
          ])
        }
        onAdd={(value) => {
          setTags((prev) => [...prev, { id: `custom-${value}`, label: value }]);
          setText("");
        }}
        onRemoveTag={(id) =>
          setTags((prev) => prev.filter((tag) => tag.id !== id))
        }
      />
    </div>
  );
}

/** Closed set: only options can be chosen; typing filters. */
export const ClosedSet: Story = {
  render: () => <ControlledWithOptions />,
};

/** Open set: options plus free entry via the create row. */
export const OpenSet: Story = {
  render: () => <ControlledWithOptions mode="open" />,
};
