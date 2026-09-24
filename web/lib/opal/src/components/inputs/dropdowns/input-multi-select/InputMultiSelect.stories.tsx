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

function ControlledSelect() {
  const [tags, setTags] = useState<TagItem[]>([]);
  return (
    <div className="w-96">
      <InputMultiSelect
        tags={tags}
        options={GROUP_OPTIONS}
        placeholder="Pick groups…"
        onSelectOption={(option) =>
          setTags((prev) => [
            ...prev,
            { id: option.value, label: option.label },
          ])
        }
        onRemoveTag={(id) =>
          setTags((prev) => prev.filter((tag) => tag.id !== id))
        }
      />
    </div>
  );
}

/** Chips only, no filter text; the full set always shows. */
export const Default: Story = {
  render: () => <ControlledSelect />,
};
