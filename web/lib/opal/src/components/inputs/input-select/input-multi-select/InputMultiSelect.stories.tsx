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

function ControlledInputTags(
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
  render: () => <ControlledInputTags />,
};

export const WithIcon: Story = {
  render: () => <ControlledInputTags icon={SvgTag} />,
};

export const WithClear: Story = {
  render: () => <ControlledInputTags onClear={() => {}} />,
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
  render: () => <ControlledInputTags variant="internal" />,
};

export const Disabled: Story = {
  render: () => <ControlledInputTags disabled />,
};
