import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { importGitHubSkills, previewGitHubSkills } from "@/lib/skills/api";
import type { CustomSkill } from "@/lib/skills/types";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useUser } from "@/providers/UserProvider";
import { FetchError } from "@/lib/fetcher";

jest.mock("@/lib/skills/api", () => ({
  importGitHubSkills: jest.fn(),
  previewGitHubSkills: jest.fn(),
}));
jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: { success: jest.fn() },
}));
jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: jest.fn(),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: jest.fn(),
}));

const mockedPreviewGitHubSkills = jest.mocked(previewGitHubSkills);
const mockedImportGitHubSkills = jest.mocked(importGitHubSkills);
const mockedUseUserExternalApps = jest.mocked(useUserExternalApps);
const mockedUseUser = jest.mocked(useUser);
const githubApp = {
  id: 7,
  name: "GitHub",
  description: "GitHub access",
  slug: "github",
  app_type: "GITHUB" as const,
  credential_keys: ["access_token"],
  credential_values: {},
  authenticated: false,
  supports_oauth: true,
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

  it("previews repository skills and imports only the selected paths", async () => {
    const user = userEvent.setup();
    mockedPreviewGitHubSkills.mockResolvedValue({
      repository: "owner/repo",
      revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      subpath: null,
      skills: [
        {
          path: "skills/alpha",
          name: "Alpha",
          description: "First skill",
          unavailable_reason: null,
        },
        {
          path: "skills/beta",
          name: "Beta",
          description: "Second skill",
          unavailable_reason: null,
        },
        {
          path: "skills/pptx",
          name: "pptx",
          description: "Create and edit presentations",
          unavailable_reason:
            "Can't import: 'pptx' is a reserved skill name in Onyx.",
        },
      ],
    });
    mockedImportGitHubSkills.mockResolvedValue([
      { name: "Alpha" } as CustomSkill,
    ]);
    const onCreated = jest.fn();

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={onCreated}
      />
    );

    await user.type(
      screen.getByRole("textbox"),
      "https://github.com/owner/repo"
    );
    await user.click(screen.getByRole("button", { name: "Search repository" }));

    expect(await screen.findByText("3 skills found")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select Alpha" })
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Select pptx" })
    ).toHaveAttribute("data-disabled", "true");
    expect(
      screen.getByText("Can't import: 'pptx' is a reserved skill name in Onyx.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Select Beta" }));
    await user.click(screen.getByRole("button", { name: "Import skill" }));

    await waitFor(() => {
      expect(mockedImportGitHubSkills).toHaveBeenCalledWith(
        "owner/repo",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        null,
        ["skills/alpha"]
      );
    });
    expect(onCreated).toHaveBeenCalledWith([{ name: "Alpha" }]);
  });

  it("offers the existing GitHub connection flow for private repositories", () => {
    mockedUseUserExternalApps.mockReturnValue({
      data: [githubApp],
      error: undefined,
      isLoading: false,
      refresh: jest.fn(),
    });

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    expect(
      screen.getByText(
        "Public repositories don't require a GitHub connection. Connect GitHub to import private repositories."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Connect GitHub" })
    ).toHaveAttribute("href", "/craft/v1/apps?connect=github");
    expect(
      screen.getByRole("link", { name: "Connect GitHub" })
    ).not.toHaveAttribute("target");
  });

  it("explains the admin prerequisite when GitHub is not configured", () => {
    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    expect(
      screen.getByText(
        "Public repositories don't require a GitHub connection. Ask a workspace admin to set up the GitHub App to import private repositories."
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Connect GitHub" })
    ).not.toBeInTheDocument();
  });

  it("links admins directly to GitHub App setup", () => {
    mockedUseUser.mockReturnValue({
      isAdmin: true,
    } as ReturnType<typeof useUser>);

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    expect(
      screen.getByText(
        "Public repositories don't require a GitHub connection. Set up the GitHub App to import private repositories."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up GitHub" })).toHaveAttribute(
      "href",
      "/admin/craft/apps"
    );
    expect(
      screen.getByRole("link", { name: "Set up GitHub" })
    ).not.toHaveAttribute("target");
  });

  it("quietly confirms private repository support when GitHub is connected", () => {
    mockedUseUserExternalApps.mockReturnValue({
      data: [{ ...githubApp, authenticated: true }],
      error: undefined,
      isLoading: false,
      refresh: jest.fn(),
    });

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    expect(
      screen.getByText(
        "You can import public repositories and any private repositories your GitHub account can access."
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Connect GitHub" })
    ).not.toBeInTheDocument();
  });

  it("shows a preview failure next to the repository controls", async () => {
    const user = userEvent.setup();
    mockedPreviewGitHubSkills.mockRejectedValueOnce(
      new FetchError(
        "No SKILL.md files were found in this repository. Add a SKILL.md file, then try again.",
        404,
        { error_code: "NOT_FOUND" }
      )
    );

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    await user.type(screen.getByRole("textbox"), "owner/repository");
    await user.click(screen.getByRole("button", { name: "Search repository" }));

    expect(
      await screen.findByText("Couldn’t load repository")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No SKILL.md files were found in this repository. Add a SKILL.md file, then try again."
      )
    ).toBeInTheDocument();
  });

  it("keeps the preview and retries a transient import failure", async () => {
    const user = userEvent.setup();
    mockedPreviewGitHubSkills.mockResolvedValueOnce({
      repository: "owner/repository",
      revision: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      subpath: null,
      skills: [
        {
          path: "skills/research",
          name: "Research",
          description: "Research a topic",
          unavailable_reason: null,
        },
      ],
    });
    mockedImportGitHubSkills.mockRejectedValue(
      new FetchError(
        "GitHub's API rate limit has been reached. Try again in a few minutes.",
        429,
        { error_code: "RATE_LIMITED" }
      )
    );

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    await user.type(screen.getByRole("textbox"), "owner/repository");
    await user.click(screen.getByRole("button", { name: "Search repository" }));
    await user.click(
      await screen.findByRole("button", { name: "Import skill" })
    );

    expect(
      await screen.findByText("Couldn’t import skills")
    ).toBeInTheDocument();
    expect(screen.getByText("1 skill found")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(mockedImportGitHubSkills).toHaveBeenCalledTimes(2)
    );
  });

  it("links an expired GitHub connection to reauthorization", async () => {
    const user = userEvent.setup();
    mockedUseUserExternalApps.mockReturnValue({
      data: [{ ...githubApp, authenticated: true }],
      error: undefined,
      isLoading: false,
      refresh: jest.fn(),
    });
    mockedPreviewGitHubSkills.mockRejectedValueOnce(
      new FetchError(
        "Your GitHub connection has expired. Reconnect GitHub, then try again.",
        401,
        { error_code: "UNAUTHENTICATED" }
      )
    );

    render(
      <ImportSkillsFromGitHubModal
        open
        onClose={jest.fn()}
        onCreated={jest.fn()}
      />
    );

    await user.type(screen.getByRole("textbox"), "owner/private-repository");
    await user.click(screen.getByRole("button", { name: "Search repository" }));

    expect(
      await screen.findByRole("link", { name: "Reconnect GitHub" })
    ).toHaveAttribute("href", "/craft/v1/apps?connect=github");
  });
});
