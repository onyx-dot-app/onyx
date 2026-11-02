import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import BulkSkillSharingModal from "@/sections/modals/skills/BulkSkillSharingModal";

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ isAdmin: true }),
}));
jest.mock("@/hooks/useShareableUsers", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));
jest.mock("@/hooks/useShareableGroups", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
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
});
