import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { Permission, type MinimalUserSnapshot } from "@/lib/types";
import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

let mockShareableUsers: MinimalUserSnapshot[] = [];
let mockShareableGroups: MinimalUserGroupSnapshot[] = [];
let mockIsAdmin = true;
let mockPermissions: string[] = [];
let mockAdminCapabilities: string[] = [];
const mockUpdateSkillShares = jest.fn();
const mockResetAccess = jest.fn();
const mockLoadSkill = jest.fn();
jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual<typeof import("@/lib/fetcher")>("@/lib/fetcher"),
  errorHandlingFetcher: (...args: unknown[]) => mockLoadSkill(...args),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    isAdmin: mockIsAdmin,
    user: null,
    permissions: mockIsAdmin
      ? [Permission.FULL_ADMIN_PANEL_ACCESS]
      : mockPermissions,
    adminCapabilities: mockAdminCapabilities,
  }),
}));
jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: () => ({ data: mockShareableUsers }),
}));
jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: () => ({ data: mockShareableGroups }),
}));
jest.mock("@/lib/skills/api", () => ({
  ...jest.requireActual("@/lib/skills/api"),
  updateSkillShares: (...args: unknown[]) => mockUpdateSkillShares(...args),
  transferSkillOwnership: jest.fn(),
  resetSkillMarketplaceAccess: (...args: unknown[]) => mockResetAccess(...args),
}));

describe("ShareSkillModal", () => {
  beforeEach(() => {
    mockShareableUsers = [];
    mockShareableGroups = [];
    mockIsAdmin = true;
    mockPermissions = [];
    mockAdminCapabilities = [];
    mockLoadSkill
      .mockReset()
      .mockResolvedValue(customFixture({ user_permission: "OWNER" }));
    mockUpdateSkillShares.mockReset().mockResolvedValue({});
    mockResetAccess.mockReset();
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

  it("preserves sharing edits through restore, blocks closing while pending and refreshes details", async () => {
    const user = setupUser();
    mockShareableUsers = [{ id: "new-person", email: "new@example.com" }];
    const onClose = jest.fn();
    const onSaved = jest.fn();
    let current = {
      ...customFixture({
        user_permission: "OWNER",
        public_permission: null,
        current_version_number: 2,
      }),
      instructions_markdown: "Current instructions",
      files: [],
    };
    mockLoadSkill.mockImplementation(async () => current);
    const request = deferred<Response>();
    let attempts = 0;
    const fetchMock = jest.fn(
      async (url: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          attempts += 1;
          if (attempts === 1) return request.promise;
          current = {
            ...current,
            current_version_number: 3,
            instructions_markdown: "Restored instructions",
          };
          return new Response(JSON.stringify(current));
        }
        return new Response(
          JSON.stringify([
            {
              id: "v1",
              version_number: 1,
              created_at: "2026-11-08T12:00:00Z",
              created_by: null,
              is_current: false,
              has_bundle: true,
              marketplace_revision: null,
            },
          ])
        );
      }
    );
    global.fetch = fetchMock;
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={onClose}
        onSaved={onSaved}
      />
    );
    await user.click(await screen.findByRole("button", { name: "Required" }));
    await user.type(
      screen.getByRole("combobox", { name: "Add users, groups, and accounts" }),
      "new@example.com"
    );
    await screen.findByRole("option", { name: /new@example.com/ });
    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(screen.getByRole("tab", { name: "Versions" }));
    await user.click(
      await screen.findByRole("button", { name: "Restore version 1" })
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getByRole("tab", { name: "Details" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Sharing" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(
      screen
        .getAllByRole("button", { name: "Cancel" })
        .every((button) => button.hasAttribute("disabled"))
    ).toBe(true);
    await user.keyboard("{Escape}");
    fireEvent.pointerDown(document.body);
    expect(onClose).not.toHaveBeenCalled();
    await act(async () =>
      request.resolve(
        new Response(
          JSON.stringify({
            detail: "Version files changed. Retry this request.",
          }),
          { status: 409 }
        )
      )
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Version files changed. Retry this request."
    );
    expect(onSaved).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Selected version content is now current."
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "Versions" })).toHaveFocus();
    await user.click(screen.getByRole("tab", { name: "Details" }));
    expect(await screen.findByText("Restored instructions")).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "Sharing" }));
    expect(screen.getByRole("button", { name: "Required" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({
          installation_policy: "REQUIRED",
          user_shares: [{ user_id: "new-person", permission: "VIEWER" }],
        })
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

  it("shows a saved Not available policy as selected and can change it", async () => {
    const user = setupUser();
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "OWNER",
        installation_policy: "NOT_AVAILABLE",
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
      await screen.findByRole("button", { name: "Not available" })
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Available to install" })
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText(/Hidden from the library and the agent/)
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Available to install" })
    );
    await user.click(screen.getByRole("button", { name: "Not available" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: "Installed by default" })
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({ installation_policy: "DEFAULT" })
      )
    );
  });

  describe("group installation settings", () => {
    const groupShares = [
      {
        group_id: 1,
        group_name: "Engineering",
        permission: "VIEWER",
        installation_policy: "NOT_AVAILABLE",
      },
      {
        group_id: 2,
        group_name: "Support",
        permission: "VIEWER",
        installation_policy: "REQUIRED",
      },
      {
        group_id: 3,
        group_name: "Research",
        permission: "EDITOR",
        installation_policy: null,
      },
    ] as const;

    function renderEdit(overrides: Parameters<typeof customFixture>[0] = {}) {
      mockLoadSkill.mockResolvedValue(
        customFixture({
          user_permission: "OWNER",
          public_permission: null,
          group_shares: groupShares.map((share) => ({ ...share })),
          ...overrides,
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
    }

    async function choosePolicy(group: string, option: RegExp) {
      const user = setupUser();
      await user.click(
        await screen.findByRole("button", { name: `Installation for ${group}` })
      );
      fireEvent.click(screen.getByRole("option", { name: option }));
    }

    it("sends only changed overrides: set, cleared and untouched", async () => {
      const user = setupUser();
      renderEdit();
      expect(
        await screen.findByRole("button", {
          name: "Installation for Engineering",
        })
      ).toHaveTextContent("Not available");
      expect(
        screen.getByRole("button", { name: "Installation for Research" })
      ).toHaveTextContent("Company setting");
      await choosePolicy("Support", /^Company setting/);
      await choosePolicy("Research", /^Not available/);
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(mockUpdateSkillShares).toHaveBeenCalledWith(
          "custom-1",
          expect.objectContaining({
            group_shares: [
              { group_id: 1, permission: "VIEWER" },
              { group_id: 2, permission: "VIEWER", installation_policy: null },
              {
                group_id: 3,
                permission: "EDITOR",
                installation_policy: "NOT_AVAILABLE",
              },
            ],
          })
        )
      );
    });

    it("treats choosing the saved override again as unchanged", async () => {
      renderEdit();
      await choosePolicy("Support", /^Installed by default/);
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
      await choosePolicy("Support", /^Required/);
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("adds a new group without an override unless one is chosen", async () => {
      mockShareableGroups = [{ id: 9, name: "Design" }];
      const user = setupUser();
      renderEdit({ group_shares: [] });
      await user.type(
        await screen.findByRole("combobox", {
          name: "Add users, groups, and accounts",
        }),
        "des"
      );
      fireEvent.click(await screen.findByRole("option", { name: /Design/ }));
      expect(
        screen.getByRole("button", { name: "Installation for Design" })
      ).toHaveTextContent("Company setting");
      await choosePolicy("Design", /^Required/);
      const chip = screen.getAllByText("Design")[0]?.parentElement;
      if (!chip) throw new Error("Missing staged group chip");
      await user.click(within(chip).getByRole("button"));
      await user.type(
        screen.getByRole("combobox", {
          name: "Add users, groups, and accounts",
        }),
        "des"
      );
      fireEvent.click(await screen.findByRole("option", { name: /Design/ }));
      expect(
        screen.getByRole("button", { name: "Installation for Design" })
      ).toHaveTextContent("Company setting");
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(mockUpdateSkillShares).toHaveBeenCalledWith(
          "custom-1",
          expect.objectContaining({
            group_shares: [{ group_id: 9, permission: "VIEWER" }],
          })
        )
      );
    });

    it("keeps a non-manager owner from changing or dropping a saved override", async () => {
      mockIsAdmin = false;
      const user = setupUser();
      renderEdit();
      expect(
        await screen.findByRole("button", {
          name: "Installation for Engineering",
        })
      ).toBeDisabled();
      await user.click(
        screen.getByRole("button", { name: "Update access for Engineering" })
      );
      expect(
        screen.queryByRole("option", { name: "Remove Access" })
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("option", { name: /Can edit/ }));
      await user.click(
        screen.getByRole("button", { name: "Update access for Research" })
      );
      fireEvent.click(
        await screen.findByRole("option", { name: "Remove Access" })
      );
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(mockUpdateSkillShares).toHaveBeenCalledWith(
          "custom-1",
          expect.objectContaining({
            group_shares: [
              { group_id: 1, permission: "EDITOR" },
              { group_id: 2, permission: "VIEWER" },
            ],
          })
        )
      );
    });

    it.each([
      { visibility: null, editable: true },
      { visibility: "VIEWER", editable: false },
    ] as const)(
      "lets a scoped manager edit overrides only on private skills ($visibility)",
      async ({ visibility, editable }) => {
        mockIsAdmin = false;
        mockAdminCapabilities = [Permission.MANAGE_SKILLS];
        renderEdit({ public_permission: visibility });
        const user = setupUser();
        if (visibility !== null) {
          await user.click(
            await screen.findByRole("button", {
              name: "Manage individual access",
            })
          );
        }
        const menu = await screen.findByRole("button", {
          name: "Installation for Engineering",
        });
        if (editable) expect(menu).toBeEnabled();
        else expect(menu).toBeDisabled();
      }
    );

    it("hides the section from a non-manager when no group has an override", async () => {
      mockIsAdmin = false;
      renderEdit({
        group_shares: [
          {
            group_id: 3,
            group_name: "Research",
            permission: "EDITOR",
            installation_policy: null,
          },
        ],
      });
      await screen.findByText("Research");
      expect(screen.queryByText("Group Installation")).not.toBeInTheDocument();
    });
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

  it.each(["OWNER", "EDITOR"] as const)(
    "lets non-global %s save invitations without clearing public access",
    async (permission) => {
      mockIsAdmin = false;
      mockLoadSkill.mockResolvedValue(
        customFixture({
          user_permission: permission,
          owner: { id: "owner", email: "owner@example.com" },
          author_user_id: "owner",
          ownership_vacant: false,
          public_permission: "VIEWER",
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
      await user.click(
        await screen.findByRole("button", { name: "Manage individual access" })
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
    }
  );

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
            {
              group_id: 42,
              group_name: "Editors",
              permission: "EDITOR",
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
  it.each(["basic owner", "scoped manager", "permissions loading"])(
    "disables company visibility for %s without disabling individual access",
    async (actor) => {
      mockIsAdmin = false;
      mockAdminCapabilities =
        actor === "scoped manager" ? [Permission.MANAGE_SKILLS] : [];
      render(
        <ShareSkillModal
          mode="create"
          open
          draft={customFixture({
            user_permission: "OWNER",
            public_permission: null,
          })}
          onClose={jest.fn()}
          onSaveDraft={jest.fn()}
        />
      );
      expect(
        screen.getByRole("button", { name: "Change sharing scope" })
      ).toBeDisabled();
      expect(
        screen.queryByRole("group", { name: "Installation" })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("combobox", {
          name: "Add users, groups, and accounts",
        })
      ).toBeEnabled();
    }
  );

  it("lets a global skill manager without full admin set company policy", async () => {
    mockIsAdmin = false;
    mockPermissions = [Permission.MANAGE_SKILLS];
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
    await user.click(await screen.findByRole("button", { name: "Required" }));
    expect(
      screen.getByRole("button", { name: "Change sharing scope" })
    ).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({
          installation_policy: "REQUIRED",
          public_permission: "VIEWER",
        })
      )
    );
  });

  const companySource = {
    id: "company-source",
    name: "Team tools",
    personal: false,
    follows_access: false,
    can_share: true,
    folder: "skills/reports",
  };

  it("lets scoped managers edit ownerless group grants but not individual grants", async () => {
    mockIsAdmin = false;
    mockAdminCapabilities = [Permission.MANAGE_SKILLS];
    mockShareableUsers = [{ id: "alice", email: "alice@example.com" }];
    mockShareableGroups = [{ id: 7, name: "Engineering" }];
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "EDITOR",
        public_permission: null,
        marketplace: companySource,
        user_shares: [
          {
            user: { id: "bob", email: "bob@example.com" },
            permission: "VIEWER",
          },
        ],
        group_shares: [
          {
            group_id: 7,
            group_name: "Engineering",
            permission: "VIEWER",
            installation_policy: null,
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
    const search = await screen.findByRole("combobox", {
      name: "Add users, groups, and accounts",
    });
    await user.type(search, "alice");
    expect(
      screen.queryByRole("option", { name: /alice@example.com/ })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Update access for bob@example.com" })
    ).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: "Update access for Engineering" })
    );
    fireEvent.click(screen.getByRole("option", { name: "Can edit" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(mockUpdateSkillShares).toHaveBeenCalledWith(
        "custom-1",
        expect.objectContaining({
          user_shares: [{ user_id: "bob", permission: "VIEWER" }],
          group_shares: [{ group_id: 7, permission: "EDITOR" }],
        })
      )
    );
  });

  it("keeps company sharing read-only for an editor without management permission", async () => {
    mockIsAdmin = false;
    mockPermissions = [];
    mockAdminCapabilities = [];
    mockLoadSkill.mockResolvedValue(
      customFixture({
        user_permission: "EDITOR",
        public_permission: "EDITOR",
        marketplace: { ...companySource, can_share: false },
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
      await screen.findByRole("button", { name: "Change sharing scope" })
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Save" })
    ).not.toBeInTheDocument();
  });

  it.each([false, true])(
    "lets a personal synced owner publish without installation authority (scoped=%s)",
    async (scoped) => {
      mockIsAdmin = false;
      mockPermissions = [];
      mockAdminCapabilities = scoped ? [Permission.MANAGE_SKILLS] : [];
      mockLoadSkill.mockResolvedValue(
        customFixture({
          user_permission: "OWNER",
          public_permission: null,
          marketplace: { ...companySource, personal: true },
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
        await screen.findByRole("option", {
          name: "Anyone in your organization",
        })
      );
      expect(
        screen.queryByRole("group", { name: "Installation" })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /transfer ownership/i })
      ).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() =>
        expect(mockUpdateSkillShares).toHaveBeenLastCalledWith("custom-1", {
          public_permission: "VIEWER",
          installation_policy: undefined,
          user_shares: [],
          group_shares: [],
        })
      );
    }
  );

  it.each([false, true])(
    "locks personal synced audience for a non-owner (global=%s)",
    async (global) => {
      mockIsAdmin = false;
      mockPermissions = global ? [Permission.MANAGE_SKILLS] : [];
      mockAdminCapabilities = [];
      mockLoadSkill.mockResolvedValue(
        customFixture({
          user_permission: "EDITOR",
          public_permission: null,
          group_shares: [
            {
              group_id: 1,
              group_name: "Support",
              permission: "VIEWER",
              installation_policy: "DEFAULT",
            },
          ],
          user_shares: [
            {
              user: { id: "editor", email: "editor@example.com" },
              permission: "EDITOR",
            },
          ],
          marketplace: { ...companySource, personal: true, can_share: global },
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
      expect(
        await screen.findByRole("button", { name: "Change sharing scope" })
      ).toBeDisabled();
      expect(
        screen.getByRole("button", {
          name: "Update access for editor@example.com",
        })
      ).toBeDisabled();
      expect(
        screen.queryByRole("combobox", {
          name: "Add users, groups, and accounts",
        })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Reset to marketplace access" })
      ).not.toBeInTheDocument();
      const groupPolicy = screen.getByRole("button", {
        name: "Installation for Support",
      });
      expect(
        screen.getByRole("button", { name: "Update access for Support" })
      ).toBeDisabled();
      if (global) {
        expect(groupPolicy).toBeEnabled();
        await user.click(groupPolicy);
        fireEvent.click(screen.getByRole("option", { name: /^Not available/ }));
        await user.click(screen.getByRole("button", { name: "Required" }));
        await user.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() =>
          expect(mockUpdateSkillShares).toHaveBeenLastCalledWith("custom-1", {
            public_permission: undefined,
            installation_policy: "REQUIRED",
            user_shares: [{ user_id: "editor", permission: "EDITOR" }],
            group_shares: [
              {
                group_id: 1,
                permission: "VIEWER",
                installation_policy: "NOT_AVAILABLE",
              },
            ],
          })
        );
      } else {
        expect(groupPolicy).toBeDisabled();
        expect(
          screen.queryByRole("button", { name: "Save" })
        ).not.toBeInTheDocument();
      }
    }
  );

  it.each(["following", "scoped", "retired"])(
    "does not offer reset for %s company skills",
    async (state) => {
      mockIsAdmin = state !== "scoped";
      mockPermissions = [];
      mockAdminCapabilities =
        state === "scoped" ? [Permission.MANAGE_SKILLS] : [];
      mockLoadSkill.mockResolvedValue(
        customFixture({
          user_permission: "EDITOR",
          retired_at: state === "retired" ? "2026-11-08T00:00:00Z" : null,
          marketplace: {
            ...companySource,
            follows_access: state === "following",
          },
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
      expect(
        screen.queryByRole("button", { name: "Reset to marketplace access" })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /transfer ownership/i })
      ).not.toBeInTheDocument();
    }
  );

  it("confirms reset, locks dismissal while pending, and replaces the draft with saved defaults", async () => {
    mockShareableUsers = [];
    mockShareableGroups = [];
    mockIsAdmin = true;
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "EDITOR", marketplace: companySource })
    );
    let finishReset: (skill: ReturnType<typeof customFixture>) => void = () => {
      throw new Error("Reset not started");
    };
    mockResetAccess.mockImplementation(
      () =>
        new Promise<ReturnType<typeof customFixture>>((resolve) => {
          finishReset = resolve;
        })
    );
    const user = setupUser();
    const onClose = jest.fn();
    const onSaved = jest.fn();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={onClose}
        onSaved={onSaved}
      />
    );
    await user.click(await screen.findByRole("button", { name: "Required" }));
    await user.click(
      screen.getByRole("button", { name: "Reset to marketplace access" })
    );
    expect(
      screen.getByText(/removes individual grants and discards unsaved changes/)
    ).toBeVisible();
    expect(document.activeElement).toHaveTextContent(
      "removes individual grants"
    );
    expect(mockResetAccess).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Required" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await user.click(
      screen.getByRole("button", { name: "Reset to marketplace access" })
    );
    await user.click(screen.getByRole("button", { name: "Reset access" }));
    expect(mockResetAccess).toHaveBeenCalledTimes(1);
    expect(mockResetAccess).toHaveBeenCalledWith("custom-1");
    expect(screen.getByRole("button", { name: "Reset access" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    finishReset(
      customFixture({
        user_permission: "EDITOR",
        installation_policy: "DEFAULT",
        marketplace: { ...companySource, follows_access: true },
      })
    );
    expect(await screen.findByText("Follows Marketplace Access")).toBeVisible();
    expect(document.activeElement).toHaveTextContent(
      "Follows Marketplace Access"
    );
    expect(
      screen.getByRole("button", { name: "Installed by default" })
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(mockUpdateSkillShares).not.toHaveBeenCalled();
  });

  it("keeps a failed reset open for retry without discarding the sharing draft", async () => {
    mockShareableUsers = [];
    mockShareableGroups = [];
    mockIsAdmin = true;
    mockLoadSkill.mockResolvedValue(
      customFixture({ user_permission: "EDITOR", marketplace: companySource })
    );
    mockResetAccess
      .mockReset()
      .mockRejectedValueOnce(new Error("Access is being changed. Try again."));
    const onSaved = jest.fn();
    const user = setupUser();
    render(
      <ShareSkillModal
        mode="edit"
        skillId="custom-1"
        open
        onClose={jest.fn()}
        onSaved={onSaved}
      />
    );
    await user.click(await screen.findByRole("button", { name: "Required" }));
    await user.click(
      screen.getByRole("button", { name: "Reset to marketplace access" })
    );
    await user.click(screen.getByRole("button", { name: "Reset access" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Access is being changed. Try again."
    );
    expect(screen.getByRole("button", { name: "Reset access" })).toBeEnabled();
    expect(onSaved).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Required" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});
