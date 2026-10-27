import { render, screen, setupUser } from "@tests/setup/test-utils";
import { ResetPasswordModal } from "@/views/admin/UsersPage/UserActionModals";
import { resetPassword } from "@/views/admin/UsersPage/svc";

jest.mock("@/views/admin/UsersPage/svc", () => ({
  ...jest.requireActual("@/views/admin/UsersPage/svc"),
  resetPassword: jest.fn(),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

const mockResetPassword = resetPassword as jest.MockedFunction<
  typeof resetPassword
>;

describe("ResetPasswordModal", () => {
  it("warns that sessions end and personal access tokens are revoked", () => {
    render(<ResetPasswordModal email="user@example.com" onClose={() => {}} />);

    expect(
      screen.getByText(/signed out of all sessions/i, { exact: false })
    ).toHaveTextContent("their personal access tokens will be revoked");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("shows only Done after the reset succeeds", async () => {
    mockResetPassword.mockResolvedValue({
      user_id: "1",
      new_password: "new-random-password",
    });
    const user = setupUser();
    render(<ResetPasswordModal email="user@example.com" onClose={() => {}} />);

    await user.click(screen.getByRole("button", { name: "Reset Password" }));

    expect(
      await screen.findByDisplayValue("new-random-password")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" })
    ).not.toBeInTheDocument();
  });
});
