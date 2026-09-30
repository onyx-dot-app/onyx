import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputTypeInTag, type TagItem } from "@opal/components";
import { SvgTag } from "@opal/icons";

const meta: Meta<typeof InputTypeInTag> = {
  title: "opal/components/InputTypeInTag",
  component: InputTypeInTag,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputTypeInTag>;

function ControlledInputTypeInTag({
  initialTags = [
    { id: "1", label: "Tag" },
    { id: "2", label: "2" },
  ],
  ...props
}: Partial<React.ComponentProps<typeof InputTypeInTag>> & {
  initialTags?: TagItem[];
}) {
  const [tags, setTags] = useState<TagItem[]>(initialTags);
  const [value, setValue] = useState("");

  return (
    <div className="w-80">
      <InputTypeInTag
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
  render: () => <ControlledInputTypeInTag />,
};

export const WithIcon: Story = {
  render: () => <ControlledInputTypeInTag icon={SvgTag} />,
};

export const WithClear: Story = {
  render: () => <ControlledInputTypeInTag onClear={() => {}} />,
};

export const WithError: Story = {
  render: () => {
    const tags: TagItem[] = [
      { id: "1", label: "valid" },
      { id: "2", label: "not-an-email", error: true },
    ];
    return (
      <div className="w-80">
        <InputTypeInTag
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

/** Past `maxRows` (two by default) the chips scroll inside the field. */
export const ManyTags: Story = {
  render: () => {
    const tags: TagItem[] = Array.from({ length: 30 }, (_, i) => ({
      id: String(i + 1),
      label: `Team ${String(i + 1).padStart(2, "0")}`,
    }));
    return <ControlledInputTypeInTag initialTags={tags} />;
  },
};

export const Subtle: Story = {
  render: () => <ControlledInputTypeInTag variant="internal" />,
};

export const Disabled: Story = {
  render: () => <ControlledInputTypeInTag disabled />,
};
