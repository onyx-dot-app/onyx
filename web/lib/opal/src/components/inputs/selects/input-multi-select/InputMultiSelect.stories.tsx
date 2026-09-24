import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputMultiSelect, type TagItem } from "@opal/components";

const meta: Meta<typeof InputMultiSelect> = {
  title: "opal/components/InputMultiSelect",
  component: InputMultiSelect,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputMultiSelect>;

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
