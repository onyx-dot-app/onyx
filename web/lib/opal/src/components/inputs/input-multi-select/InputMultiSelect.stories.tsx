import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { InputMultiSelect } from "@opal/components";
import SvgUsers from "@opal/icons/users";
import SvgLogOut from "@opal/icons/log-out";

const meta: Meta<typeof InputMultiSelect> = {
  title: "opal/components/InputMultiSelect",
  component: InputMultiSelect,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof InputMultiSelect>;

const GROUPS = [
  { id: "1", title: "Engineering", description: "14 members", icon: SvgUsers },
  { id: "2", title: "Design", description: "5 members", icon: SvgUsers },
  { id: "3", title: "Sales", description: "9 members", icon: SvgUsers },
  { id: "4", title: "Support", description: "7 members", icon: SvgUsers },
  { id: "5", title: "Leadership", description: "3 members", icon: SvgUsers },
];

function Controlled(props: { initial?: string[]; disabled?: boolean }) {
  const [value, setValue] = useState<string[]>(props.initial ?? []);
  return (
    <div className="w-96">
      <InputMultiSelect
        items={GROUPS}
        value={value}
        onChange={setValue}
        placeholder="Search groups…"
        removeIcon={SvgLogOut}
        disabled={props.disabled}
      />
    </div>
  );
}

/** Empty selection shows the EmptyMessageCard. */
export const Default: Story = {
  render: () => <Controlled />,
};

export const WithSelection: Story = {
  render: () => <Controlled initial={["1", "3"]} />,
};

export const Disabled: Story = {
  render: () => <Controlled initial={["2"]} disabled />,
};

export const Loading: Story = {
  render: () => {
    const [value, setValue] = useState<string[]>([]);
    return (
      <div className="w-96">
        <InputMultiSelect
          items={[]}
          value={value}
          onChange={setValue}
          placeholder="Search groups…"
          loading
        />
      </div>
    );
  },
};
