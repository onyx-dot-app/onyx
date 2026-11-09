import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { Permission } from "@/lib/types";
import BulkSkillSharingModal from "@/sections/modals/skills/BulkSkillSharingModal";

let mockPermissions: string[] = [];

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    isAdmin: false,
    permissions: mockPermissions,
    adminCapabilities: [Permission.MANAGE_SKILLS],
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
  default: () => ({ data: [{ id: 7, name: "Cash Kings" }] }),
}));

describe("BulkSkillSharingModal", () => {
  beforeEach(() => {
    mockPermissions = [Permission.MANAGE_SKILLS];
  });
  it("shares all selected skills organization-wide without changing their installation policy", async () => {
    const user = setupUser();
    const onSave = jest.fn().mockResolvedValue(undefined);
    render(
      <BulkSkillSharingModal
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
  it("keeps staged edits across a generic close and drops them on Cancel", async () => {
    const user = setupUser();
    const onClose = jest.fn();
    const props = {
      count: 2,
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
    fireEvent.click(screen.getByRole("option", { name: "Required" }));
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
