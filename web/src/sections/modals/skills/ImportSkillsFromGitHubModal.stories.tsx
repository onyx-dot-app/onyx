import type { Meta, StoryObj } from "@storybook/react";
import { FetchError } from "@/lib/fetcher";
import { ImportSkillsFromGitHubModalView } from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

const githubApp: ExternalAppUserResponse = {
  id: 7,
  name: "GitHub",
  description: "GitHub access",
  slug: "github",
  app_type: "GITHUB",
  credential_keys: ["access_token"],
  credential_values: {},
  authenticated: false,
  supports_oauth: true,
};

const preview = {
  repository: "onyx-dot-app/skills",
  skills: [
    {
      path: "skills/deep-research",
      name: "Deep Research",
      description: "Research a topic thoroughly and report the findings.",
      unavailable_reason: null,
    },
    {
      path: "skills/code-review",
      name: "Code Review",
      description: "Review a change for correctness and maintainability.",
      unavailable_reason: null,
    },
  ],
};

function apiError(errorCode: string, message: string, status: number) {
  return new FetchError(message, status, {
    error_code: errorCode,
    detail: message,
  });
}

const meta: Meta<typeof ImportSkillsFromGitHubModalView> = {
  title: "Sections/Skills/Import Skills from GitHub Modal",
  component: ImportSkillsFromGitHubModalView,
  parameters: { layout: "fullscreen" },
  args: {
    open: true,
    onClose: () => undefined,
    repository: "",
    preview: null,
    selectedPaths: [],
    loading: false,
    error: null,
    isAdmin: false,
    externalApps: [],
    onRepositoryChange: () => undefined,
    onSelectedPathsChange: () => undefined,
    onSubmit: () => undefined,
  },
};

export default meta;
type Story = StoryObj<typeof ImportSkillsFromGitHubModalView>;

export const PublicRepository: Story = {};

export const AdminCanSetUpGitHub: Story = {
  args: { isAdmin: true },
};

export const PrivateRepositoryCanConnect: Story = {
  args: { externalApps: [githubApp] },
};

export const GitHubConnected: Story = {
  args: {
    externalApps: [{ ...githubApp, authenticated: true }],
  },
};

export const SearchingRepository: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/skills",
    loading: true,
  },
};

export const SkillsFound: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/skills",
    preview,
    selectedPaths: preview.skills.map((skill) => skill.path),
  },
};

export const ReservedNameAmongSkills: Story = {
  args: {
    repository: "https://github.com/anthropics/skills",
    preview: {
      repository: "anthropics/skills",
      skills: [
        {
          path: "skills/pptx",
          name: "pptx",
          description: "Create and edit presentation files.",
          unavailable_reason:
            "Can't import: 'pptx' is a reserved skill name in Onyx.",
        },
        {
          path: "skills/pdf",
          name: "PDF",
          description: "Create and edit PDF files.",
          unavailable_reason: null,
        },
      ],
    },
    selectedPaths: ["skills/pdf"],
  },
};

export const NoImportableSkills: Story = {
  args: {
    repository: "https://github.com/example/presentation-skill",
    preview: {
      repository: "example/presentation-skill",
      skills: [
        {
          path: ".",
          name: "pptx",
          description: "Create and edit presentation files.",
          unavailable_reason:
            "Can't import: 'pptx' is a reserved skill name in Onyx.",
        },
      ],
    },
    selectedPaths: [],
  },
};

export const ImportingSkills: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/skills",
    preview,
    selectedPaths: preview.skills.map((skill) => skill.path),
    loading: true,
  },
};

export const NoSkillFound: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/empty-repository",
    error: apiError(
      "NOT_FOUND",
      "No SKILL.md files were found in this repository. Add a SKILL.md file, then try again.",
      404
    ),
  },
};

export const InvalidSkillFile: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/skills",
    error: apiError(
      "INVALID_INPUT",
      "Invalid SKILL.md at 'skills/research/SKILL.md': SKILL.md frontmatter must include a non-empty 'description'",
      400
    ),
  },
};

export const RepositoryTooLarge: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/skills",
    error: apiError(
      "PAYLOAD_TOO_LARGE",
      "Repository download exceeds the 25 MiB limit. Remove large files or move the skills to a smaller repository.",
      413
    ),
  },
};

export const GitHubConnectionExpired: Story = {
  args: {
    repository: "onyx-dot-app/private-skills",
    externalApps: [{ ...githubApp, authenticated: true }],
    error: apiError(
      "UNAUTHENTICATED",
      "Your GitHub connection has expired. Reconnect GitHub, then try again.",
      401
    ),
  },
};

export const GitHubAccessDenied: Story = {
  args: {
    repository: "onyx-dot-app/private-skills",
    externalApps: [{ ...githubApp, authenticated: true }],
    error: apiError(
      "INSUFFICIENT_PERMISSIONS",
      "GitHub denied access to this repository. Make sure your connected account has access and, if required, has authorized organization SSO.",
      403
    ),
  },
};

export const GitHubRateLimited: Story = {
  args: {
    repository: "onyx-dot-app/skills",
    externalApps: [{ ...githubApp, authenticated: true }],
    error: apiError(
      "RATE_LIMITED",
      "GitHub's API rate limit has been reached. Try again in a few minutes.",
      429
    ),
  },
};

export const ImportNameConflict: Story = {
  args: {
    repository: "https://github.com/onyx-dot-app/skills",
    preview,
    selectedPaths: preview.skills.map((skill) => skill.path),
    error: apiError(
      "DUPLICATE_RESOURCE",
      'A skill named "Deep Research" already exists in this workspace. Rename it in SKILL.md, then try again.',
      409
    ),
  },
};
