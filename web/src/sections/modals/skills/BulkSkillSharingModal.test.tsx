import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { Permission } from "@/lib/types";
import BulkSkillSharingModal from "@/sections/modals/skills/BulkSkillSharingModal";

let mockPermissions: string[] = [];
let mockCapabilities: string[] = [];

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    isAdmin: false,
    permissions: mockPermissions,
    adminCapabilities: mockCapabilities,
  }),
}));
jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: () => ({
    data: [
      { id: "user-1", email: "subash@onyx.app" },
      { id: "user-2", email: "thomas@onyx.app" },
    ],
  }),
}));
jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: () => ({
    data: [
      { id: 7, name: "Cash Kings" },
      { id: 8, name: "Night Owls" },
      { id: 9, name: "Early Birds" },
    ],
  }),
}));

describe("BulkSkillSharingModal", () => {
  beforeEach(() => {
    mockPermissions = [Permission.MANAGE_SKILLS];
    mockCapabilities = [Permission.MANAGE_SKILLS];
  });

  async function stageGroup(name: string) {
    const user = setupUser();
    await user.type(
      screen.getByRole("combobox", { name: "Add users, groups, and accounts" }),
      name.slice(0, 4)
    );
    fireEvent.click(
      await screen.findByRole("option", { name: new RegExp(name) })
    );
  }

  function renderModal(props: { onSave: jest.Mock; following?: number }) {
    render(
      <BulkSkillSharingModal
        count={3}
        followingMarketplaceCount={props.following}
        canChangeUserAccess
        canChangeOrgAccess
        open
        saving={false}
        onClose={jest.fn()}
        onSave={props.onSave}
      />
    );
  }

  it("adds groups and sends only the settings chosen for them", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    renderModal({ onSave });
    expect(screen.queryByText("Group Installation")).not.toBeInTheDocument();
    await stageGroup("Cash Kings");
    await stageGroup("Night Owls");
    await stageGroup("Early Birds");
    expect(
      screen.getByRole("button", { name: "Installation for Cash Kings" })
    ).toHaveTextContent("Keep unchanged");
    await user.click(
      screen.getByRole("button", { name: "Installation for Night Owls" })
    );
    fireEvent.click(screen.getByRole("option", { name: /^Not available/ }));
    await user.click(
      screen.getByRole("button", { name: "Installation for Early Birds" })
    );
    fireEvent.click(screen.getByRole("option", { name: /^Company setting/ }));
    await user.click(screen.getByRole("button", { name: "Apply to 3 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        group_shares: [
          { group_id: 7, permission: "VIEWER" },
          {
            group_id: 8,
            permission: "VIEWER",
            installation_policy: "NOT_AVAILABLE",
          },
          { group_id: 9, permission: "VIEWER", installation_policy: null },
        ],
      })
    );
  });

  it("drops a removed group's setting", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    renderModal({ onSave });
    await stageGroup("Cash Kings");
    await user.click(
      screen.getByRole("button", { name: "Installation for Cash Kings" })
    );
    fireEvent.click(screen.getByRole("option", { name: /^Required/ }));
    // The staged chip comes first; its remove button has no name of its own.
    const chip = screen.getAllByText("Cash Kings")[0]!.parentElement!;
    await user.click(within(chip).getByRole("button"));
    expect(
      screen.queryByRole("button", { name: "Installation for Cash Kings" })
    ).not.toBeInTheDocument();
    await stageGroup("Cash Kings");
    expect(
      screen.getByRole("button", { name: "Installation for Cash Kings" })
    ).toHaveTextContent("Keep unchanged");
  });

  it("offers group settings to scoped managers but not to members", async () => {
    mockPermissions = [];
    const onSave = jest.fn().mockResolvedValue(undefined);
    const { unmount } = render(
      <BulkSkillSharingModal
        count={2}
        canChangeUserAccess={false}
        canChangeOrgAccess={false}
        open
        saving={false}
        onClose={jest.fn()}
        onSave={onSave}
      />
    );
    await stageGroup("Cash Kings");
    expect(
      screen.getByRole("button", { name: "Installation for Cash Kings" })
    ).toBeEnabled();
    unmount();
    mockCapabilities = [];
    renderModal({ onSave });
    await stageGroup("Cash Kings");
    expect(
      screen.queryByRole("button", { name: "Installation for Cash Kings" })
    ).not.toBeInTheDocument();
    await setupUser().click(
      screen.getByRole("button", { name: "Apply to 3 skills" })
    );
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        group_shares: [{ group_id: 7, permission: "VIEWER" }],
      })
    );
  });

  it("warns before detaching skills that follow a company marketplace", () => {
    renderModal({ onSave: jest.fn(), following: 2 });
    expect(
      screen.getByText(
        "2 selected skills follow their company marketplace. Saving gives them their own access, and later syncs keep that access."
      )
    ).toBeVisible();
  });

  it("shows no detach warning without following skills", () => {
    renderModal({ onSave: jest.fn() });
    expect(
      screen.queryByText(/follow their company marketplace/)
    ).not.toBeInTheDocument();
  });

  it("keeps group sharing available when selected skills forbid individual grants", async () => {
    mockPermissions = [];
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    render(
      <BulkSkillSharingModal
        count={2}
        canChangeUserAccess={false}
        canChangeOrgAccess={false}
        open
        saving={false}
        onClose={jest.fn()}
        onSave={onSave}
      />
    );
    const search = screen.getByRole("combobox", {
      name: "Add users, groups, and accounts",
    });
    await user.type(search, "sub");
    expect(
      screen.queryByRole("option", { name: /subash@onyx.app/ })
    ).not.toBeInTheDocument();
    await user.clear(search);
    await stageGroup("Cash Kings");
    await user.click(screen.getByRole("button", { name: "Apply to 2 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        group_shares: [{ group_id: 7, permission: "VIEWER" }],
      })
    );
  });

  it("omits staged people if the selection stops allowing individual grants", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    const props = {
      count: 2,
      canChangeOrgAccess: false,
      open: true,
      saving: false,
      onClose: jest.fn(),
      onSave,
    };
    const { rerender } = render(
      <BulkSkillSharingModal {...props} canChangeUserAccess />
    );
    const search = screen.getByRole("combobox", {
      name: "Add users, groups, and accounts",
    });
    await user.type(search, "sub");
    fireEvent.click(
      await screen.findByRole("option", { name: /subash@onyx.app/ })
    );
    rerender(<BulkSkillSharingModal {...props} canChangeUserAccess={false} />);
    expect(
      screen.getByRole("button", { name: "Apply to 2 skills" })
    ).toBeDisabled();
    await stageGroup("Cash Kings");
    await user.click(screen.getByRole("button", { name: "Apply to 2 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        group_shares: [{ group_id: 7, permission: "VIEWER" }],
      })
    );
  });

  it("shares all selected skills organization-wide without changing their installation policy", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    render(
      <BulkSkillSharingModal
        canChangeUserAccess
        count={80}
        canChangeOrgAccess
        open
        saving={false}
        onClose={jest.fn()}
        onSave={onSave}
      />
    );
    expect(
      screen.getByRole("button", { name: "Apply to 80 skills" })
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Who can access" }));
    fireEvent.click(
      screen.getByRole("option", { name: "Everyone in the organization" })
    );
    await user.click(
      screen.getByRole("button", { name: "Apply to 80 skills" })
    );
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({ public_permission: "VIEWER" })
    );
  });
  it("offers Not available as a company installation policy", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    render(
      <BulkSkillSharingModal
        count={2}
        canChangeOrgAccess
        canChangeUserAccess
        open
        saving={false}
        onClose={jest.fn()}
        onSave={onSave}
      />
    );
    await user.click(screen.getByRole("button", { name: "Installation" }));
    fireEvent.click(screen.getByRole("option", { name: /^Not available/ }));
    await user.click(screen.getByRole("button", { name: "Apply to 2 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        installation_policy: "NOT_AVAILABLE",
      })
    );
  });
  it("keeps staged edits across a generic close and drops them on Cancel", async () => {
    const user = setupUser();
    const onClose = jest.fn();
    const props = {
      count: 2,
      canChangeUserAccess: true,
      canChangeOrgAccess: true,
      saving: false,
      onClose,
      onSave: jest.fn(),
    };
    const { rerender } = render(<BulkSkillSharingModal open {...props} />);
    await user.click(screen.getByRole("button", { name: "Who can access" }));
    fireEvent.click(
      screen.getByRole("option", { name: "Everyone in the organization" })
    );
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
    onClose.mockClear();
    rerender(<BulkSkillSharingModal open={false} {...props} />);
    rerender(<BulkSkillSharingModal open {...props} />);
    expect(
      screen.getByRole("button", { name: "Apply to 2 skills" })
    ).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    rerender(<BulkSkillSharingModal open={false} {...props} />);
    rerender(<BulkSkillSharingModal open {...props} />);
    expect(
      screen.getByRole("button", { name: "Apply to 2 skills" })
    ).toBeDisabled();
  });
  it("adds people picked from the suggestion list to every selected skill", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    render(
      <BulkSkillSharingModal
        canChangeUserAccess
        count={2}
        canChangeOrgAccess
        open
        saving={false}
        onClose={jest.fn()}
        onSave={onSave}
      />
    );
    const search = screen.getByRole("combobox", {
      name: "Add users, groups, and accounts",
    });
    await user.type(search, "sub");
    expect(
      screen.queryByRole("option", { name: /thomas@onyx\.app/ })
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("option", { name: /subash@onyx\.app/ })
    );
    expect(search).toHaveValue("");
    await user.type(search, "cash");
    fireEvent.click(await screen.findByRole("option", { name: /Cash Kings/ }));
    await user.click(screen.getByRole("button", { name: "Apply to 2 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        user_shares: [{ user_id: "user-1", permission: "VIEWER" }],
        group_shares: [{ group_id: 7, permission: "VIEWER" }],
      })
    );
  });
  it("drops staged company changes when global authority is lost, but keeps group invitations", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    const props = {
      count: 2,
      canChangeUserAccess: true,
      canChangeOrgAccess: true,
      open: true,
      saving: false,
      onClose: jest.fn(),
      onSave,
    };
    const { rerender } = render(<BulkSkillSharingModal {...props} />);
    await user.click(screen.getByRole("button", { name: "Who can access" }));
    fireEvent.click(
      screen.getByRole("option", { name: "Everyone in the organization" })
    );
    await user.click(screen.getByRole("button", { name: "Installation" }));
    fireEvent.click(screen.getByRole("option", { name: /^Required/ }));
    await user.type(
      screen.getByRole("combobox", { name: "Add users, groups, and accounts" }),
      "cash"
    );
    fireEvent.click(await screen.findByRole("option", { name: /Cash Kings/ }));
    rerender(<BulkSkillSharingModal {...props} canChangeOrgAccess={false} />);
    expect(
      screen.getByRole("button", { name: "Who can access" })
    ).toHaveTextContent("Keep unchanged");
    rerender(<BulkSkillSharingModal {...props} />);
    mockPermissions = [];
    rerender(<BulkSkillSharingModal {...props} />);
    expect(
      screen.getByRole("button", { name: "Who can access" })
    ).toHaveTextContent("Keep unchanged");
    expect(
      screen.getByRole("button", { name: "Who can access" })
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Installation" })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply to 2 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        group_shares: [{ group_id: 7, permission: "VIEWER" }],
      })
    );
  });
});
