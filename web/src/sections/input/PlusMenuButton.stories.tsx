import type { Meta, StoryObj } from "@storybook/react";
import { Text } from "@opal/components";
import { SvgPaperclip, SvgSparkle, SvgPlug } from "@opal/icons";
import { SvgSlack, SvgGmail } from "@opal/logos";
import {
  PlusMenuButton,
  type PlusMenuItem,
} from "@/sections/input/PlusMenuButton";

const skillsFlyout: PlusMenuItem["flyoutItems"] = [
  {
    key: "pptx",
    icon: SvgSparkle,
    label: "PPTX",
    description: "Build PowerPoint decks.",
    onSelect: () => console.log("select pptx"),
  },
  {
    key: "pdf",
    icon: SvgSparkle,
    label: "PDF",
    description: "Fill and read PDFs.",
    onSelect: () => console.log("select pdf"),
  },
  {
    key: "report-writer",
    icon: SvgSparkle,
    label: "Report Writer",
    description: "Draft a structured report from notes.",
    onSelect: () => console.log("select report-writer"),
  },
];

const appsFlyout: PlusMenuItem["flyoutItems"] = [
  {
    key: "slack",
    icon: SvgSlack,
    label: "Slack",
    onSelect: () => console.log("select slack"),
  },
  {
    key: "gmail",
    icon: SvgGmail,
    label: "Gmail",
    rightContent: (
      <Text font="secondary-body" color="text-03">
        Connect
      </Text>
    ),
    onSelect: () => console.log("select gmail"),
  },
];

const filesItem: PlusMenuItem = {
  key: "files",
  icon: SvgPaperclip,
  label: "Add files or photos",
  onSelect: () => console.log("attach files"),
};

const skillsItem: PlusMenuItem = {
  key: "skills",
  icon: SvgSparkle,
  label: "Skills",
  flyoutItems: skillsFlyout,
};

const appsItem: PlusMenuItem = {
  key: "apps",
  icon: SvgPlug,
  label: "Apps",
  flyoutItems: appsFlyout,
};

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
};

export default meta;
type Story = StoryObj<typeof PlusMenuButton>;

export const Default: Story = {
  args: { items: [filesItem, null, skillsItem, appsItem] },
};

export const SkillsOnly: Story = {
  args: { items: [filesItem, null, skillsItem] },
};

export const ActionsOnly: Story = {
  args: { items: [filesItem] },
};

export const Disabled: Story = {
  args: { items: [filesItem, null, skillsItem, appsItem], disabled: true },
};
