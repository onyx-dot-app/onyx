import type { Meta, StoryObj } from "@storybook/react";
import { PlusMenuButton } from "@/sections/input/PlusMenuButton";
import {
  appFixture,
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import { toPickerSections } from "@/lib/skills/picker";
import type { SkillsList } from "@/refresh-pages/admin/SkillsPage/interfaces";

const skillsList: SkillsList = {
  builtins: [builtinFixture(), builtinFixture({ slug: "pdf", name: "PDF" })],
  customs: [customFixture()],
};

const apps = [
  appFixture({ slug: "slack", app_type: "SLACK" }),
  appFixture({ slug: "gmail", app_type: "GMAIL", authenticated: false }),
];

const fullSections = toPickerSections(skillsList, apps);
const skillsOnlySections = toPickerSections(skillsList, []);
const emptySections = toPickerSections(undefined, undefined);

const meta: Meta<typeof PlusMenuButton> = {
  title: "Apps/Craft/Input Bar/Plus Menu Button",
  component: PlusMenuButton,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[400px] p-8 flex justify-start">
        <Story />
      </div>
    ),
  ],
  args: {
    onSelectEntry: (e) => console.log("select", e),
    onAttachFiles: () => console.log("attach files"),
  },
};

export default meta;
type Story = StoryObj<typeof PlusMenuButton>;

export const Default: Story = {
  args: { sections: fullSections },
};

export const SkillsOnly: Story = {
  args: { sections: skillsOnlySections },
};

export const EmptySections: Story = {
  args: { sections: emptySections },
};

export const Disabled: Story = {
  args: { sections: fullSections, disabled: true },
};
