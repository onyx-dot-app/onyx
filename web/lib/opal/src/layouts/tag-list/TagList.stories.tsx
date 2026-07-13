import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { type TagItem } from "@opal/components";
import { TagList } from "@opal/layouts";
import { SvgTag } from "@opal/icons";

const meta: Meta<typeof TagList> = {
  title: "opal/layouts/TagList",
  component: TagList,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof TagList>;

const ITEMS: TagItem[] = [
  { id: "1", label: "design" },
  { id: "2", label: "engineering" },
  { id: "3", label: "a very long label that gets truncated" },
  { id: "4", label: "ops" },
  { id: "5", label: "research" },
];

export const Default: Story = {
  render: () => {
    const [items, setItems] = useState(ITEMS);
    return (
      <div className="w-96">
        <TagList
          items={items}
          onRemove={(id) => setItems((prev) => prev.filter((i) => i.id !== id))}
        />
      </div>
    );
  },
};

export const MaxVisible: Story = {
  render: () => {
    const [items, setItems] = useState(ITEMS);
    return (
      <div className="w-96">
        <TagList
          items={items}
          maxVisible={3}
          overflowIcon={SvgTag}
          onRemove={(id) => setItems((prev) => prev.filter((i) => i.id !== id))}
        />
      </div>
    );
  },
};

export const Passive: Story = {
  render: () => (
    <div className="w-96">
      <TagList items={ITEMS.slice(0, 3)} />
    </div>
  ),
};
