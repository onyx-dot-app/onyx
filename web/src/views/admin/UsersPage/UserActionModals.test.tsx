import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { FetchError } from "@/lib/fetcher";
import {
  DeleteUserModal,
  ResetPasswordModal,
} from "@/views/admin/UsersPage/UserActionModals";
import { deleteUser, resetPassword } from "@/views/admin/UsersPage/svc";

const mockGo = jest.fn();

jest.mock("@/views/admin/UsersPage/svc", () => ({
  ...jest.requireActual("@/views/admin/UsersPage/svc"),
  deleteUser: jest.fn(),
  resetPassword: jest.fn(),
}));

jest.mock("@opal/navigation", () => ({
  ...jest.requireActual("@opal/navigation"),
  useNavigation: () => ({ go: mockGo }),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

const mockDeleteUser = deleteUser as jest.MockedFunction<typeof deleteUser>;
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

describe("DeleteUserModal", () => {
  const conflictDetail =
    "Transfer or delete this user's private skills before deleting the user.";

  function renderModal() {
    render(
      <DeleteUserModal
        email="user@example.com"
        onClose={() => {}}
        onMutate={() => {}}
      />
    );
  }

  it("links to the skills page when private skills block the delete", async () => {
    mockDeleteUser.mockRejectedValue(
      new FetchError(conflictDetail, 409, {
        error_code: "CONFLICT",
        detail: conflictDetail,
      })
    );
    const errorToast = jest.spyOn(toast, "error").mockReturnValue("toast-id");
    const user = setupUser();
    renderModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(errorToast).toHaveBeenCalled());
    const [message, options] = errorToast.mock.calls[0]!;
    expect(message).toBe(conflictDetail);
    expect(options?.duration).toBe(Infinity);
    options?.action?.onClick();
    expect(mockGo).toHaveBeenCalledWith("/admin/skills");
    errorToast.mockRestore();
  });

  it("shows no action for other delete errors", async () => {
    mockDeleteUser.mockRejectedValue(new Error("Error deleting user"));
    const errorToast = jest.spyOn(toast, "error").mockReturnValue("toast-id");
    const user = setupUser();
    renderModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(errorToast).toHaveBeenCalled());
    expect(errorToast.mock.calls[0]![1]?.action).toBeUndefined();
    errorToast.mockRestore();
  });
});
