import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { importGitHubSkills, previewGitHubSkills } from "@/lib/skills/api";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useUser } from "@/providers/UserProvider";
import type { GitHubSkillsPreview } from "@/lib/skills/types";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

jest.mock("@/lib/skills/api", () => ({
  importGitHubSkills: jest.fn(),
  previewGitHubSkills: jest.fn(),
}));
jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: jest.fn(),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: jest.fn(),
}));

const mockedPreview = jest.mocked(previewGitHubSkills);
const mockedImport = jest.mocked(importGitHubSkills);
const mockedUseUserExternalApps = jest.mocked(useUserExternalApps);
const mockedUseUser = jest.mocked(useUser);

const preview: GitHubSkillsPreview = {
  repository: "owner/repository",
  revision: "a".repeat(40),
  subpath: null,
  skills: [
    {
      path: "skills/alpha",
      name: "alpha",
      description: "First skill",
      unavailable_reason: null,
    },
    {
      path: "skills/beta",
      name: "beta",
      description: "Second skill",
      unavailable_reason: null,
    },
    {
      path: "skills/pptx",
      name: "pptx",
      description: "Create presentations",
      unavailable_reason: "A built-in Onyx skill already uses this name.",
    },
  ],
};

describe("ImportSkillsFromGitHubModal", () => {
  beforeEach(() => {
    mockedUseUser.mockReturnValue({
      isAdmin: false,
    } as ReturnType<typeof useUser>);
    mockedUseUserExternalApps.mockReturnValue({
      data: [],
      error: undefined,
      isLoading: false,
      refresh: jest.fn(),
    });
  });

  it("imports selected skills and explains every outcome", async () => {
    const user = userEvent.setup();
    const onImported = jest.fn();
    mockedPreview.mockResolvedValue(preview);
    mockedImport.mockResolvedValue({
      imported: [
        {
          skill: customFixture({
            id: "alpha-id",
            name: "alpha",
            description: "First skill",
          }),
          enabled: true,
          disabled_reason: null,
        },
      ],
      not_imported: [],
    });

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onImported={onImported}
      />
    );

    await user.type(screen.getByRole("textbox"), "owner/repository");
    await user.click(screen.getByRole("button", { name: "Search repository" }));

    expect(
      await screen.findByText("2 of 2 importable skills selected")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select pptx" })
    ).toHaveAttribute("data-disabled", "true");
    await user.click(screen.getByRole("checkbox", { name: "Select beta" }));
    await user.click(screen.getByRole("button", { name: "Import skill" }));

    await waitFor(() =>
      expect(mockedImport).toHaveBeenCalledWith(preview, ["skills/alpha"])
    );
    expect(await screen.findByText("1 skill imported")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Not imported")).toBeInTheDocument();
    expect(
      screen.getByText("A built-in Onyx skill already uses this name.")
    ).toBeInTheDocument();
    expect(screen.getByText(/1 not selected/)).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("shows name conflicts as successful disabled imports", async () => {
    const user = userEvent.setup();
    mockedPreview.mockResolvedValue({
      ...preview,
      skills: [preview.skills[0]!],
    });
    mockedImport.mockResolvedValue({
      imported: [
        {
          skill: customFixture({
            id: "alpha-copy",
            name: "alpha",
            description: "First skill",
            enabled: false,
          }),
          enabled: false,
          disabled_reason: "Another skill named “alpha” is already enabled.",
        },
      ],
      not_imported: [],
    });

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onImported={jest.fn()}
      />
    );
    await user.type(screen.getByRole("textbox"), "owner/repository");
    await user.click(screen.getByRole("button", { name: "Search repository" }));
    await user.click(
      await screen.findByRole("button", { name: "Import skill" })
    );

    expect(await screen.findByText("1 skill imported")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
    expect(
      screen.getByText("Another skill named “alpha” is already enabled.")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 imported disabled because another skill/)
    ).toBeInTheDocument();
  });

  it("links users to GitHub when private repository access is available", () => {
    mockedUseUserExternalApps.mockReturnValue({
      data: [
        {
          id: 7,
          name: "GitHub",
          app_type: "GITHUB",
          credential_keys: ["access_token"],
          credential_values: {},
          authenticated: false,
          supports_oauth: true,
        },
      ],
      error: undefined,
      isLoading: false,
      refresh: jest.fn(),
    });

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onImported={jest.fn()}
      />
    );

    expect(
      screen.getByText(
        "Public repositories import directly. Connect GitHub to import private repositories."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Connect GitHub" })
    ).toHaveAttribute("href", "/craft/v1/apps");
    expect(
      screen.getByRole("link", { name: "Connect GitHub" })
    ).not.toHaveAttribute("target");
  });
});
