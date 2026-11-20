import { renderHook } from "@testing-library/react";
import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { FetchError } from "@/lib/fetcher";
import { AccountType } from "@/lib/types";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import type { FullUserSnapshot } from "@/views/admin/UsersPage/types";
import {
  DeleteUserModal,
  ResetPasswordModal,
  useClosePrivateSkillsToastOnLeave,
} from "@/views/admin/UsersPage/UserActionModals";
import {
  deleteUser,
  resetPassword,
  transferPrivatePlugins,
} from "@/views/admin/UsersPage/svc";

const mockGo = jest.fn();

jest.mock("@/views/admin/UsersPage/svc", () => ({
  ...jest.requireActual("@/views/admin/UsersPage/svc"),
  deleteUser: jest.fn(),
  resetPassword: jest.fn(),
  transferPrivatePlugins: jest.fn(),
}));

jest.mock("@opal/navigation", () => ({
  ...jest.requireActual("@opal/navigation"),
  useNavigation: () => ({ go: mockGo }),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

const mockDeleteUser = deleteUser as jest.MockedFunction<typeof deleteUser>;
const mockTransferPrivatePlugins =
  transferPrivatePlugins as jest.MockedFunction<typeof transferPrivatePlugins>;
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
  const conflictBody = {
    error_code: "CONFLICT",
    detail: conflictDetail,
    private_plugins: [
      { id: "p1", name: "deploy" },
      { id: "p2", name: "review" },
    ],
  };

  function account(
    id: string,
    email: string,
    overrides: Partial<FullUserSnapshot> = {}
  ): FullUserSnapshot {
    return {
      id,
      email,
      account_type: AccountType.STANDARD,
      is_admin: false,
      is_active: true,
      password_configured: true,
      personal_name: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      last_active: null,
      groups: [],
      is_scim_synced: false,
      craft_enabled: null,
      ...overrides,
    };
  }

  beforeEach(() => {
    mockFetch({
      "/api/manage/users/accepted/all": [
        account("leaver-id", "user@example.com"),
        account("heir-id", "heir@example.com"),
        account("gone-id", "gone@example.com", { is_active: false }),
        account("bot-id", "bot@example.com", {
          account_type: AccountType.BOT,
        }),
      ],
    });
  });

  afterEach(() => jest.restoreAllMocks());

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
    expect(message).toBe("Can't delete this user");
    expect(options?.description).toBe(conflictDetail);
    expect(options?.duration).toBe(Infinity);
    const dismiss = jest.spyOn(toast, "dismiss");
    options?.action?.onClick();
    expect(mockGo).toHaveBeenCalledWith("/admin/skills");
    expect(dismiss).not.toHaveBeenCalled();
    errorToast.mockRestore();
    dismiss.mockRestore();
  });

  it("transfers all private plugins to one active user, then deletes", async () => {
    mockDeleteUser
      .mockRejectedValueOnce(new FetchError(conflictDetail, 409, conflictBody))
      .mockResolvedValueOnce();
    mockTransferPrivatePlugins.mockResolvedValue({
      plugin_ids: ["p1", "p2"],
      renames: [{ plugin_id: "p1", old_name: "deploy", new_name: "deploy-2" }],
    });
    const errorToast = jest.spyOn(toast, "error");
    const infoToast = jest.spyOn(toast, "info").mockReturnValue("toast-id");
    const onClose = jest.fn();
    const user = setupUser();
    render(
      <DeleteUserModal
        email="user@example.com"
        onClose={onClose}
        onMutate={() => {}}
      />
    );

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("deploy")).toBeInTheDocument();
    expect(screen.getByText("review")).toBeInTheDocument();
    expect(errorToast).not.toHaveBeenCalled();
    const submit = screen.getByRole("button", {
      name: "Transfer All and Delete",
    });
    expect(submit).toBeDisabled();

    await user.type(screen.getByPlaceholderText("Add a user or group"), "@");
    for (const blocked of [
      "user@example.com",
      "gone@example.com",
      "bot@example.com",
    ])
      expect(
        screen.queryByRole("option", { name: blocked })
      ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "heir@example.com" }));
    await user.click(submit);

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mockTransferPrivatePlugins).toHaveBeenCalledWith(
      "user@example.com",
      "heir-id"
    );
    expect(mockDeleteUser).toHaveBeenCalledTimes(2);
    expect(infoToast.mock.calls[0]![1]?.description).toBe("deploy → deploy-2");
    errorToast.mockRestore();
    infoToast.mockRestore();
  });

  it("reports the renames when the delete fails after the transfer", async () => {
    mockDeleteUser
      .mockRejectedValueOnce(new FetchError(conflictDetail, 409, conflictBody))
      .mockRejectedValueOnce(new Error("Error deleting user"));
    mockTransferPrivatePlugins.mockResolvedValue({
      plugin_ids: ["p1", "p2"],
      renames: [{ plugin_id: "p1", old_name: "deploy", new_name: "deploy-2" }],
    });
    const errorToast = jest.spyOn(toast, "error").mockReturnValue("toast-id");
    const infoToast = jest.spyOn(toast, "info").mockReturnValue("toast-id");
    const user = setupUser();
    renderModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.type(
      await screen.findByPlaceholderText("Add a user or group"),
      "@"
    );
    fireEvent.click(screen.getByRole("option", { name: "heir@example.com" }));
    await user.click(
      screen.getByRole("button", { name: "Transfer All and Delete" })
    );

    await waitFor(() => expect(errorToast).toHaveBeenCalled());
    expect(infoToast.mock.calls[0]![1]?.description).toBe("deploy → deploy-2");
  });

  it("closes the private-skills toast when the delete succeeds", async () => {
    mockDeleteUser.mockResolvedValue();
    const dismiss = jest.spyOn(toast, "dismiss");
    const user = setupUser();
    renderModal();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(dismiss).toHaveBeenCalledWith("delete-user-private-skills")
    );
    dismiss.mockRestore();
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

describe("useClosePrivateSkillsToastOnLeave", () => {
  it("closes the private-skills toast when the Users page unmounts", () => {
    const { unmount } = renderHook(() => useClosePrivateSkillsToastOnLeave());
    const dismiss = jest.spyOn(toast, "dismiss");

    unmount();

    expect(dismiss).toHaveBeenCalledWith("delete-user-private-skills");
    dismiss.mockRestore();
  });
});
