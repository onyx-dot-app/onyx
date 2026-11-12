import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

let mockIsAdmin = true;
let mockPublishing = "OPEN";
let mockIsManager = false;
const mockUpdateSkillShares = jest.fn();
const mockLoadSkill = jest.fn();
jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: (...args: unknown[]) => mockLoadSkill(...args),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ isAdmin: mockIsAdmin, user: null }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ plugin_publishing: mockPublishing }),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockIsAdmin || mockIsManager,
    isScopedManager: false,
  }),
}));
jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));
jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));
jest.mock("@/lib/skills/api", () => ({
  updateSkillShares: (...args: unknown[]) => mockUpdateSkillShares(...args),
  transferSkillOwnership: jest.fn(),
}));

describe("ShareSkillModal", () => {
  beforeEach(() => {
    mockIsAdmin = true;
    mockIsManager = false;
    mockLoadSkill
      .mockReset()
      .mockResolvedValue(customFixture({ user_permission: "OWNER" }));
    mockUpdateSkillShares.mockReset().mockResolvedValue({});
  });

  it("keeps sharing edits while switching between the details and sharing tabs", async () => {
    mockLoadSkill.mockImplementation(async (url: string) => ({
      ...customFixture({ user_permission: "OWNER" }),
      ...(url.endsWith("/preview")
        ? { instructions_markdown: "Use the team workflow." }
        : {}),
    }));
    const user = setupUser();
    const onClose = jest.fn();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        initialTab="details"
        open
        onClose={onClose}
        onSaved={jest.fn()}
      />
    );
    await screen.findByText("Use the team workflow.");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await user.click(screen.getByRole("tab", { name: "Sharing" }));
    await user.click(screen.getByRole("button", { name: "Required" }));
    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(screen.getByText("Use the team workflow.")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Sharing" }));
    expect(screen.getByRole("button", { name: "Required" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({ installation_policy: "REQUIRED" })
      )
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("saves an admin's installation policy without changing sharing", async () => {
    const user = setupUser();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    await screen.findByText("Ownership");
    expect(screen.queryByText("People with access")).not.toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Add users, groups, and accounts")
    ).not.toBeInTheDocument();
    expect(screen.getByText("Ownership")).toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: "Installed by default" })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith("custom-1", {
        installation_policy: "DEFAULT",
        public_permission: "VIEWER",
        user_shares: [],
        group_shares: [],
      })
    );
  });

  it("loads full sharing details from the overview before saving", async () => {
    const user = setupUser();
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "OWNER",
        user_shares: [
          {
            user: { id: "invited-user", email: "invited@example.com" },
            permission: "VIEWER",
          },
        ],
      })
    );
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    await user.click(await screen.findByRole("button", { name: "Required" }));
    expect(mockLoadSkill).toHaveBeenCalledWith(
      "/api/skills/custom/custom-1/share"
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({
          user_shares: [{ user_id: "invited-user", permission: "VIEWER" }],
        })
      )
    );
  });

  it("lets non-admin editors save invitations without changing organization access", async () => {
    mockIsAdmin = false;
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "EDITOR",
        public_permission: null,
        user_shares: [
          {
            user: { id: "invitee", email: "invitee@example.com" },
            permission: "VIEWER",
          },
        ],
      })
    );
    const user = setupUser();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    await screen.findByText("invitee@example.com");
    await user.click(
      screen.getByRole("button", {
        name: "Update access for invitee@example.com",
      })
    );
    fireEvent.click(
      await screen.findByRole("option", { name: "Remove Access" })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith("custom-1", {
        installation_policy: undefined,
        public_permission: undefined,
        user_shares: [],
        group_shares: [],
      })
    );
  });

  it.each([false, true])(
    "lets owners revoke public user and group editors (app-associated: %s)",
    async (associated) => {
      const user = setupUser();
      mockLoadSkill.mockResolvedValue(
        customFixture({
          user_permission: "OWNER",
          public_permission: "VIEWER",
          external_app: associated
            ? {
                external_app_id: 1,
                name: "Discord",
                enabled: true,
                ready: true,
              }
            : null,
          user_shares: [
            {
              user: { id: "editor", email: "editor@example.com" },
              permission: "EDITOR",
            },
          ],
          group_shares: [
            { group_id: 42, group_name: "Editors", permission: "EDITOR" },
          ],
        })
      );
      render(
        <ShareSkillModal
          mode="edit"
          skillId="custom-1"
          open
          onClose={jest.fn()}
          onSaved={jest.fn()}
        />
      );
      await user.click(
        await screen.findByRole("button", { name: "Manage individual access" })
      );
      expect(screen.queryByText("People with access")).not.toBeInTheDocument();
      for (const name of ["editor@example.com", "Editors"]) {
        await user.click(
          screen.getByRole("button", { name: `Update access for ${name}` })
        );
        fireEvent.click(
          await screen.findByRole("option", { name: "Remove Access" })
        );
      }
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(mockUpdateSkillShares).toHaveBeenCalledWith(
          "custom-1",
          expect.objectContaining({
            public_permission: associated ? undefined : "VIEWER",
            user_shares: [],
            group_shares: [],
          })
        )
      );
    }
  );

  it("lets a non-admin editor with organization-wide manage:plugins publish", async () => {
    mockIsAdmin = false;
    mockIsManager = true;
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "EDITOR", public_permission: null })
    );
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    expect(
      await screen.findByRole("button", { name: "Change sharing scope" })
    ).toBeEnabled();
  });

  it("shows a published skill as Organization with no way to make it private", async () => {
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "OWNER", public_permission: "VIEWER" })
    );
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    expect(await screen.findByText("Organization")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Published. Everyone in the organization can use this skill."
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Change sharing scope" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Publishing cannot be undone")
    ).not.toBeInTheDocument();
  });

  it("shows the version history to an owner in the Versions tab", async () => {
    mockLoadSkill.mockImplementation(async (url: string) =>
      url.endsWith("/versions")
        ? [
            {
              id: "version-2",
              version_number: 2,
              created_at: "2026-11-01T10:00:00Z",
              created_by_email: "owner@example.com",
              is_current: true,
              review_status: "draft",
            },
          ]
        : customFixture({ user_permission: "OWNER" })
    );
    const user = setupUser();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    await user.click(await screen.findByRole("tab", { name: "Versions" }));
    expect(await screen.findByText("Version 2")).toBeVisible();
    expect(mockLoadSkill).toHaveBeenCalledWith(
      "/api/skills/custom/custom-1/versions"
    );
  });

  it("hides the Versions tab from a viewer", async () => {
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "VIEWER" })
    );
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    expect(await screen.findByRole("tab", { name: "Sharing" })).toBeVisible();
    expect(
      screen.queryByRole("tab", { name: "Versions" })
    ).not.toBeInTheDocument();
  });

  it("warns that publishing cannot be undone before a private skill is published", async () => {
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "OWNER", public_permission: null })
    );
    const user = setupUser();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    await user.click(
      await screen.findByRole("button", { name: "Change sharing scope" })
    );
    expect(
      screen.queryByText("Publishing cannot be undone")
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("option", { name: "Anyone in your organization" })
    );
    expect(
      await screen.findByText("Publishing cannot be undone")
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Change organization permission" })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({ public_permission: "VIEWER" })
      )
    );
  });

  it("keeps creation settings local until the skill is created", async () => {
    const user = setupUser();
    const onSaveDraft = jest.fn();
    render(
      <ShareSkillModal
        mode="create"
        draft={customFixture({ user_permission: "OWNER" })}
        open
        onClose={jest.fn()}
        onSaveDraft={onSaveDraft}
      />
    );
    await user.click(screen.getByRole("button", { name: "Required" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        installation_policy: "REQUIRED",
        public_permission: "VIEWER",
      })
    );
    expect(mockUpdateSkillShares).not.toHaveBeenCalled();
  });

  it("does not offer installation policies to non-admin owners", () => {
    mockIsAdmin = false;
    render(
      <ShareSkillModal
        mode="create"
        draft={customFixture({ user_permission: "OWNER" })}
        onSaveDraft={jest.fn()}
        open
        onClose={jest.fn()}
      />
    );
    expect(
      screen.queryByRole("group", { name: "Installation" })
    ).not.toBeInTheDocument();
  });

  it("saves installation policies for invited people and groups", async () => {
    const user = setupUser();
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "OWNER", public_permission: null })
    );
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={jest.fn()}
      />
    );
    expect(
      await screen.findByRole("group", { name: "Installation" })
    ).toBeInTheDocument();
    expect(screen.getByText("People with access")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Required" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith("custom-1", {
        installation_policy: "REQUIRED",
        public_permission: null,
        user_shares: [],
        group_shares: [],
      })
    );
  });
});
