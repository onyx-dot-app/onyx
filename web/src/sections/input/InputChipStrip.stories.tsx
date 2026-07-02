import type { Meta, StoryObj } from "@storybook/react";
import { InputChipStrip } from "@/sections/input/InputChipStrip";
import { UploadFileStatus } from "@/app/craft/contexts/UploadFilesContext";
import type { PickerEntry } from "@/lib/skills/picker";

const meta: Meta<typeof InputChipStrip> = {
  title: "Apps/Craft/Input Bar/Input Chip Strip",
  component: InputChipStrip,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px] p-4 bg-background-neutral-00 rounded-16">
        <Story />
      </div>
    ),
  ],
  args: {
    onRemoveFile: (id) => console.log("remove file", id),
    onRemoveEntry: (slug) => console.log("remove skill", slug),
    onClickEntry: (entry, el) => console.log("click skill", entry.slug, el),
    files: [],
    entries: [],
  },
};

export default meta;
type Story = StoryObj<typeof InputChipStrip>;

const SKILL_PPTX: PickerEntry = {
  kind: "skill",
  slug: "pptx",
  name: "PPTX",
  description: "Build PowerPoint decks.",
};

const SKILL_REPORT: PickerEntry = {
  kind: "skill",
  slug: "report-writer",
  name: "Report Writer",
  description: "Draft a structured report from notes.",
};

const APP_SLACK: PickerEntry = {
  kind: "app",
  slug: "slack",
  name: "Slack",
  description: "Post messages to Slack.",
  appType: "SLACK",
  authenticated: true,
};

export const FilesOnly: Story = {
  args: {
    files: [
      {
        id: "f1",
        name: "report.pdf",
        status: UploadFileStatus.COMPLETED,
        file_type: "application/pdf",
        size: 12000,
        created_at: "",
      },
      {
        id: "f2",
        name: "data.xlsx",
        status: UploadFileStatus.UPLOADING,
        file_type: "application/vnd.ms-excel",
        size: 4000,
        created_at: "",
      },
    ],
  },
};

export const SkillsOnly: Story = {
  args: {
    entries: [SKILL_PPTX, SKILL_REPORT, APP_SLACK],
  },
};

export const Mixed: Story = {
  args: {
    files: [
      {
        id: "f1",
        name: "design.png",
        status: UploadFileStatus.COMPLETED,
        file_type: "image/png",
        size: 8000,
        created_at: "",
      },
    ],
    entries: [SKILL_PPTX, APP_SLACK],
  },
};

export const Empty: Story = {
  args: { files: [], entries: [] },
};

export const WithFailedFile: Story = {
  args: {
    files: [
      {
        id: "f1",
        name: "huge.zip",
        status: UploadFileStatus.FAILED,
        file_type: "application/zip",
        size: 999_999_999,
        created_at: "",
        error: "File exceeds 50 MB limit",
      },
    ],
  },
};
