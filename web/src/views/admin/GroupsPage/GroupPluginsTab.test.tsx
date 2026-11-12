import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import GroupPluginsTab from "@/views/admin/GroupsPage/GroupPluginsTab";
import type { UserGroupPlugin } from "@/lib/groupPlugins/types";
import type { CustomSkill } from "@/lib/skills/types";

const mockSetPolicy = jest.fn();
let mockRows: UserGroupPlugin[] = [];
let mockCustoms: Partial<CustomSkill>[] = [];

jest.mock("@/lib/fetcher", () => ({
  ...jest.requireActual("@/lib/fetcher"),
  errorHandlingFetcher: async (url: string) =>
    url === "/api/skills" ? { builtins: [], customs: mockCustoms } : mockRows,
}));

jest.mock("@/lib/groupPlugins/api", () => ({
  setGroupPluginInstallationPolicy: (...args: unknown[]) =>
    mockSetPolicy(...args),
}));

function row(overrides: Partial<UserGroupPlugin>): UserGroupPlugin {
  return {
    plugin_id: "p-1",
    kind: "skill",
    name: "deploy",
    description: "Deploy the app.",
    published: false,
    permission: "VIEWER",
    installation_policy: null,
    company_installation_policy: "AVAILABLE",
    can_edit: true,
    ...overrides,
  };
}

function custom(overrides: Partial<CustomSkill>): Partial<CustomSkill> {
  return {
    source: "custom",
    id: "c-1",
    name: "review",
    description: "",
    public_permission: null,
    installation_policy: "AVAILABLE",
    company_installation_policy: "AVAILABLE",
    ...overrides,
  };
}

describe("GroupPluginsTab", () => {
  beforeEach(() => {
    mockRows = [];
    mockCustoms = [];
    mockSetPolicy.mockReset().mockImplementation(async () => mockRows);
  });

  it("shows each plugin with its setting and the inheritance text", async () => {
    mockRows = [
      row({}),
      row({
        plugin_id: "p-2",
        name: "lint",
        published: true,
        permission: null,
        installation_policy: "REQUIRED",
      }),
    ];
    render(<GroupPluginsTab groupId={7} />);

    expect(await screen.findByRole("group", { name: "deploy" })).toBeVisible();
    expect(
      screen.getByText("By default, every group uses the organization setting.")
    ).toBeVisible();
    expect(
      screen.getByText(
        "Shared with this group · Uses the organization setting: Available."
      )
    ).toBeVisible();
    expect(
      screen.getByText(
        "Group setting only · Group setting: Required. Organization setting: Available."
      )
    ).toBeVisible();
    expect(
      screen.getByRole("combobox", { name: "Setting for deploy" })
    ).toHaveValue("Organization setting (Available)");
  });

  it("saves a new setting", async () => {
    mockRows = [row({})];
    const user = setupUser();
    render(<GroupPluginsTab groupId={7} />);

    await user.click(
      await screen.findByRole("combobox", { name: "Setting for deploy" })
    );
    await user.click(screen.getByRole("option", { name: /^Required/ }));
    await waitFor(() =>
      expect(mockSetPolicy).toHaveBeenCalledWith(7, "p-1", "REQUIRED")
    );
  });

  it("removes a setting-only row and offers no remove for a share", async () => {
    mockRows = [
      row({}),
      row({
        plugin_id: "p-2",
        name: "lint",
        published: true,
        permission: null,
        installation_policy: "NOT_AVAILABLE",
      }),
    ];
    const user = setupUser();
    render(<GroupPluginsTab groupId={7} />);

    await screen.findByRole("group", { name: "lint" });
    expect(
      screen.queryByRole("button", { name: "Remove deploy from this group" })
    ).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "Remove lint from this group" })
    );
    await waitFor(() =>
      expect(mockSetPolicy).toHaveBeenCalledWith(7, "p-2", null)
    );
  });

  it("disables a row the caller cannot change", async () => {
    mockRows = [row({ can_edit: false, published: true })];
    render(<GroupPluginsTab groupId={7} />);

    expect(
      await screen.findByRole("combobox", { name: "Setting for deploy" })
    ).toBeDisabled();
    expect(
      screen.getByText(
        "Only an organization-wide plugin manager can change this setting."
      )
    ).toBeVisible();
  });

  it("adds a private plugin with the organization setting", async () => {
    mockCustoms = [custom({}), custom({ id: "p-1", name: "deploy" })];
    // The modal's select list opens in a portal outside the dialog.
    const user = setupUser({ pointerEventsCheck: 0 });
    render(<GroupPluginsTab groupId={7} />);

    expect(await screen.findByText("No plugins in this group")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Add plugins" }));
    await user.click(
      await screen.findByRole("combobox", { name: "Select a plugin" })
    );
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      expect.stringContaining("review"),
      expect.stringContaining("deploy"),
    ]);
    await user.click(screen.getByRole("option", { name: /^review/ }));
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(mockSetPolicy).toHaveBeenCalledWith(7, "c-1", null)
    );
  });

  it("needs a setting to add a published plugin", async () => {
    mockCustoms = [custom({ public_permission: "VIEWER" })];
    const user = setupUser({ pointerEventsCheck: 0 });
    render(<GroupPluginsTab groupId={7} />);

    await user.click(
      await screen.findByRole("button", { name: "Add plugins" })
    );
    await user.click(
      await screen.findByRole("combobox", { name: "Select a plugin" })
    );
    await user.click(screen.getByRole("option", { name: /^review/ }));
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();

    await user.click(
      screen.getByRole("combobox", { name: "Select a setting" })
    );
    expect(
      screen.queryByRole("option", { name: /Organization setting/ })
    ).toBeNull();
    await user.click(
      screen.getByRole("option", { name: /^Installed by default/ })
    );
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(mockSetPolicy).toHaveBeenCalledWith(7, "c-1", "DEFAULT")
    );
  });
});
