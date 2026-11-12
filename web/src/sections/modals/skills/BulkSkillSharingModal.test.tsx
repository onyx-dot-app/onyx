import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import BulkSkillSharingModal from "@/sections/modals/skills/BulkSkillSharingModal";

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    isAdmin: true,
    permissions: ["manage:plugins"],
    adminCapabilities: [],
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
    // Publishing is one-way: bulk cannot make skills private.
    expect(
      screen.queryByRole("option", { name: "Invited people and groups" })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("option", { name: "Everyone in the organization" })
    );
    expect(
      await screen.findByText("Publishing cannot be undone")
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Apply to 80 skills" })
    );
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({ public_permission: "VIEWER" })
    );
  });
  it("sets Not available for the company and a setting for each group", async () => {
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
    fireEvent.click(screen.getByRole("combobox", { name: "Installation" }));
    expect(
      screen.getByRole("option", { name: /^Default access/ })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: /^Not available/ }));

    fireEvent.click(screen.getByRole("combobox", { name: "Add a group" }));
    fireEvent.click(screen.getByRole("option", { name: "Cash Kings" }));
    const setting = screen.getByRole("combobox", {
      name: "Setting for Cash Kings",
    });
    expect(setting).toHaveValue("Organization setting");
    fireEvent.click(setting);
    fireEvent.click(screen.getByRole("option", { name: /^Required/ }));

    await user.click(screen.getByRole("button", { name: "Apply to 2 skills" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        installation_policy: "NOT_AVAILABLE",
        group_settings: [{ group_id: 7, installation_policy: "REQUIRED" }],
      })
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
});
