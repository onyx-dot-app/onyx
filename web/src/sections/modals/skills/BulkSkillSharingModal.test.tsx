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
});
