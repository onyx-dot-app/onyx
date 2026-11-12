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
const mockToast = { success: jest.fn(), info: jest.fn(), error: jest.fn() };
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
jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: {
    success: (...args: unknown[]) => mockToast.success(...args),
    info: (...args: unknown[]) => mockToast.info(...args),
    error: (...args: unknown[]) => mockToast.error(...args),
  },
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
let mockGroups: { id: number; name: string }[] = [];
jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: () => ({ data: mockGroups }),
}));
jest.mock("@/lib/skills/api", () => ({
  updateSkillShares: (...args: unknown[]) => mockUpdateSkillShares(...args),
  transferSkillOwnership: jest.fn(),
}));

async function pickCompanySetting(name: RegExp) {
  fireEvent.click(
    await screen.findByRole("combobox", { name: "Installation" })
  );
  fireEvent.click(screen.getByRole("option", { name }));
}

describe("ShareSkillModal", () => {
  beforeEach(() => {
    mockGroups = [];
    mockIsAdmin = true;
    mockPublishing = "OPEN";
    Object.values(mockToast).forEach((fn) => fn.mockReset());
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
    await pickCompanySetting(/^Required/);
    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(screen.getByText("Use the team workflow.")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Sharing" }));
    expect(screen.getByRole("combobox", { name: "Installation" })).toHaveValue(
      "Required"
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
    await pickCompanySetting(/^Installed by default/);
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
    await pickCompanySetting(/^Required/);
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
              bundle_kept: true,
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

  it("tells a non-admin author that a publish under Requires review goes to an admin", async () => {
    mockIsAdmin = false;
    mockPublishing = "REQUIRES_REVIEW";
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "OWNER", public_permission: null })
    );
    mockUpdateSkillShares.mockResolvedValue(
      customFixture({
        user_permission: "OWNER",
        public_permission: null,
        pending_version_number: 1,
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
    await user.click(
      await screen.findByRole("button", { name: "Change sharing scope" })
    );
    fireEvent.click(
      screen.getByRole("option", { name: "Anyone in your organization" })
    );
    expect(
      await screen.findByText("An admin must approve this publish")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockToast.info).toHaveBeenCalledWith(
        "Your publish request went to an admin for review."
      )
    );
    expect(mockToast.success).not.toHaveBeenCalled();
  });

  it("shows no review notice to a non-admin with organization-wide manage:plugins", async () => {
    mockIsAdmin = false;
    mockIsManager = true;
    mockPublishing = "REQUIRES_REVIEW";
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
    fireEvent.click(
      screen.getByRole("option", { name: "Anyone in your organization" })
    );
    expect(
      await screen.findByText("Publishing cannot be undone")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("An admin must approve this publish")
    ).not.toBeInTheDocument();
  });

  it("blocks a publish when the Publishing setting is Off for the user", async () => {
    mockIsAdmin = false;
    mockPublishing = "OFF";
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
    fireEvent.click(
      screen.getByRole("option", { name: "Anyone in your organization" })
    );
    expect(
      await screen.findByText("Publishing is turned off")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Publishing cannot be undone")
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(mockUpdateSkillShares).not.toHaveBeenCalled();
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
    await pickCompanySetting(/^Required/);
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
      screen.queryByRole("combobox", { name: "Installation" })
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
      await screen.findByRole("combobox", { name: "Installation" })
    ).toBeInTheDocument();
    expect(screen.getByText("People with access")).toBeInTheDocument();
    await pickCompanySetting(/^Required/);
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

  it("sends an explicit Available under a Not available default", async () => {
    const user = setupUser();
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "OWNER",
        installation_policy: null,
        default_installation_policy: "NOT_AVAILABLE",
        company_installation_policy: "NOT_AVAILABLE",
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
    expect(
      await screen.findByRole("combobox", { name: "Installation" })
    ).toHaveValue("Organization default (Not available)");
    await pickCompanySetting(/^Available to install/);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({ installation_policy: "AVAILABLE" })
      )
    );
  });

  it("sends null when an admin picks the organization default", async () => {
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
    await pickCompanySetting(/^Organization default/);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({ installation_policy: null })
      )
    );
  });

  it("saves changed group settings and leaves the company setting out", async () => {
    const user = setupUser();
    mockGroups = [
      { id: 3, name: "Design" },
      { id: 4, name: "Ops" },
      { id: 5, name: "Sales" },
    ];
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "OWNER",
        installation_policy: null,
        default_installation_policy: "AVAILABLE",
        group_summaries: [
          {
            group_id: 3,
            group_name: "Design",
            permission: "VIEWER",
            installation_policy: null,
          },
          {
            group_id: 4,
            group_name: "Ops",
            permission: null,
            installation_policy: "REQUIRED",
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
    const design = await screen.findByRole("combobox", {
      name: "Setting for Design",
    });
    expect(design).toHaveValue("Organization setting (Available to install)");
    expect(
      screen.getByRole("combobox", { name: "Setting for Ops" })
    ).toHaveValue("Required");
    // A group share has no remove button; choose the organization setting.
    expect(
      screen.queryByRole("button", { name: "Remove Design" })
    ).not.toBeInTheDocument();

    fireEvent.click(design);
    fireEvent.click(screen.getByRole("option", { name: /^Not available/ }));
    await user.click(screen.getByRole("button", { name: "Remove Ops" }));
    fireEvent.click(screen.getByRole("combobox", { name: "Add a group" }));
    fireEvent.click(screen.getByRole("option", { name: "Sales" }));
    fireEvent.click(
      screen.getByRole("combobox", { name: "Setting for Sales" })
    );
    fireEvent.click(
      screen.getByRole("option", { name: /^Installed by default/ })
    );

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdateSkillShares).toHaveBeenCalled());
    const payload = mockUpdateSkillShares.mock.calls[0][1];
    expect(payload.installation_policy).toBeUndefined();
    expect(payload.group_settings).toEqual([
      { group_id: 3, installation_policy: "NOT_AVAILABLE" },
      { group_id: 5, installation_policy: "DEFAULT" },
      { group_id: 4, installation_policy: null },
    ]);
  });

  it("hides group settings from a member without manage:plugins", async () => {
    mockIsAdmin = false;
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "OWNER",
        public_permission: null,
        group_summaries: [
          {
            group_id: 3,
            group_name: "Design",
            permission: "VIEWER",
            installation_policy: null,
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
    await screen.findByText("Ownership");
    expect(screen.queryByText("Group Access")).not.toBeInTheDocument();
  });
});
