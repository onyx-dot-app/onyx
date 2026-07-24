import type { Meta, StoryObj } from "@storybook/react";
import { ImportSkillsFromGitHubModalView } from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const revision = "a".repeat(40);
const preview = {
  repository: "anthropics/skills",
  revision,
  subpath: null,
  skills: [
    {
      path: "skills/research",
      name: "research",
      description: "Research a topic and report the findings.",
      unavailable_reason: null,
    },
    {
      path: "skills/review",
      name: "review",
      description: "Review a change for correctness and maintainability.",
      unavailable_reason: null,
    },
    {
      path: "skills/pptx",
      name: "pptx",
      description: "Create and edit presentation files.",
      unavailable_reason: "A built-in Onyx skill already uses this name.",
    },
  ],
};

const meta: Meta<typeof ImportSkillsFromGitHubModalView> = {
  title: "Sections/Skills/Import Skills from GitHub",
  component: ImportSkillsFromGitHubModalView,
  parameters: { layout: "fullscreen" },
  args: {
    open: true,
    repository: "",
    preview: null,
    selectedPaths: [],
    result: null,
    loading: false,
    error: null,
    isAdmin: false,
    externalApps: [],
    onClose: () => undefined,
    onRepositoryChange: () => undefined,
    onSelectedPathsChange: () => undefined,
    onSubmit: () => undefined,
  },
};

export default meta;
type Story = StoryObj<typeof ImportSkillsFromGitHubModalView>;

export const EnterRepository: Story = {};

export const AdminSetupRequired: Story = {
  args: {
    isAdmin: true,
  },
};

export const Searching: Story = {
  args: {
    repository: "https://github.com/anthropics/skills",
    loading: true,
  },
};

export const SkillsFound: Story = {
  args: {
    repository: "https://github.com/anthropics/skills",
    preview,
    selectedPaths: ["skills/research", "skills/review"],
  },
};

export const PartialSuccess: Story = {
  args: {
    repository: "https://github.com/anthropics/skills",
    preview,
    selectedPaths: ["skills/research", "skills/review"],
    result: {
      imported: [
        {
          skill: customFixture({
            id: "research",
            name: "research",
            description: "Research a topic and report the findings.",
          }),
          disabled_reason: null,
        },
        {
          skill: customFixture({
            id: "review",
            name: "review",
            description: "Review a change.",
            enabled: false,
          }),
          disabled_reason: "Another skill named “review” is already enabled.",
        },
      ],
      not_imported: [],
    },
  },
};

export const AllImported: Story = {
  args: {
    repository: "https://github.com/anthropics/skills",
    preview: {
      ...preview,
      skills: [preview.skills[0]!],
    },
    selectedPaths: ["skills/research"],
    result: {
      imported: [
        {
          skill: customFixture({
            id: "research",
            name: "research",
            description: "Research a topic and report the findings.",
          }),
          disabled_reason: null,
        },
      ],
      not_imported: [],
    },
  },
};

export const RepositoryError: Story = {
  args: {
    repository: "owner/private-repository",
    error:
      "Repository or branch not found. Check the URL. If the repository is private, connect GitHub and try again.",
  },
};
