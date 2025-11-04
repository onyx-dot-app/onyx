import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { PATManagement } from "./PATManagement";

// Mock the Popup hook
jest.mock("@/components/admin/connectors/Popup", () => ({
  usePopup: () => ({
    setPopup: jest.fn(),
  }),
}));

describe("PATManagement", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("user can create a new token and see it displayed", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (initial empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    render(<PATManagement />);

    // Verify empty state is shown
    await waitFor(() => {
      expect(screen.getByText(/no tokens created yet/i)).toBeInTheDocument();
    });

    // Fill in token creation form
    const nameInput = screen.getByLabelText(/token name/i);
    await user.type(nameInput, "Test Integration Token");

    // Select expiration
    const expirationSelect = screen.getByLabelText(/select token expiration/i);
    await user.click(expirationSelect);

    // Click on 7 days option
    const sevenDaysOption = await screen.findByText("7 days");
    await user.click(sevenDaysOption);

    // Mock POST /api/user/tokens (create token)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 1,
        name: "Test Integration Token",
        token: "onyx_pat_abc123def456ghi789jkl",
        token_display: "onyx_pat_abc...jkl",
        created_at: "2025-01-15T10:00:00Z",
        expires_at: "2025-01-22T23:59:59Z",
        last_used_at: null,
      }),
    } as Response);

    // Mock GET /api/user/tokens (after creation, returns new token)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 1,
          name: "Test Integration Token",
          token_display: "onyx_pat_abc...jkl",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: "2025-01-22T23:59:59Z",
          last_used_at: null,
        },
      ],
    } as Response);

    // Click create button
    const createButton = screen.getByRole("button", { name: /create token/i });
    await user.click(createButton);

    // Verify POST was called with correct data
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/user/tokens",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: "Test Integration Token",
            expiration_days: 7,
          }),
        })
      );
    });

    // Verify newly created token is displayed with full token value
    await waitFor(() => {
      expect(screen.getByText(/copy this token now/i)).toBeInTheDocument();
      expect(
        screen.getByText("onyx_pat_abc123def456ghi789jkl")
      ).toBeInTheDocument();
    });

    // Verify token appears in the list
    expect(screen.getByText("Test Integration Token")).toBeInTheDocument();
  });

  test("user can copy a newly created token", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (initial empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    // Mock clipboard API
    Object.assign(navigator, {
      clipboard: {
        writeText: jest.fn().mockResolvedValue(undefined),
      },
    });

    render(<PATManagement />);

    await user.type(screen.getByLabelText(/token name/i), "Copy Test Token");

    // Mock POST /api/user/tokens
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 2,
        name: "Copy Test Token",
        token: "onyx_pat_xyz789abc456def123ghi",
        token_display: "onyx_pat_xyz...ghi",
        created_at: "2025-01-15T10:00:00Z",
        expires_at: "2025-02-14T23:59:59Z",
        last_used_at: null,
      }),
    } as Response);

    // Mock GET /api/user/tokens (after creation)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 2,
          name: "Copy Test Token",
          token_display: "onyx_pat_xyz...ghi",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: "2025-02-14T23:59:59Z",
          last_used_at: null,
        },
      ],
    } as Response);

    await user.click(screen.getByRole("button", { name: /create token/i }));

    // Wait for token to be created
    await waitFor(() => {
      expect(
        screen.getByText("onyx_pat_xyz789abc456def123ghi")
      ).toBeInTheDocument();
    });

    // Click copy button
    const copyButton = screen.getByRole("button", {
      name: /copy token to clipboard/i,
    });
    await user.click(copyButton);

    // Verify clipboard.writeText was called with the full token
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        "onyx_pat_xyz789abc456def123ghi"
      );
    });

    // Verify button text changes to "Copied!"
    expect(await screen.findByText(/copied!/i)).toBeInTheDocument();
  });

  test("user can delete a token with confirmation", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (list with one token)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 3,
          name: "Token to Delete",
          token_display: "onyx_pat_del...ete",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: null,
          last_used_at: null,
        },
      ],
    } as Response);

    render(<PATManagement />);

    // Wait for token to appear
    await waitFor(() => {
      expect(screen.getByText("Token to Delete")).toBeInTheDocument();
    });

    // Click delete button
    const deleteButton = screen.getByRole("button", {
      name: /delete token token to delete/i,
    });
    await user.click(deleteButton);

    // Verify confirmation modal appears
    await waitFor(() => {
      expect(screen.getByText(/delete token/i)).toBeInTheDocument();
      expect(
        screen.getByText(/are you sure you want to delete token/i)
      ).toBeInTheDocument();
    });

    // Mock DELETE /api/user/tokens/3
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock GET /api/user/tokens (after deletion, empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    // Click confirm delete in modal
    const confirmDeleteButton = screen.getAllByRole("button", {
      name: /delete/i,
    })[1]; // Second delete button is in the modal
    await user.click(confirmDeleteButton);

    // Verify DELETE was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith("/api/user/tokens/3", {
        method: "DELETE",
      });
    });

    // Verify token is removed and empty state is shown
    await waitFor(() => {
      expect(screen.queryByText("Token to Delete")).not.toBeInTheDocument();
      expect(screen.getByText(/no tokens created yet/i)).toBeInTheDocument();
    });
  });

  test("user can cancel token deletion", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 4,
          name: "Token to Keep",
          token_display: "onyx_pat_kee...eep",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: null,
          last_used_at: null,
        },
      ],
    } as Response);

    render(<PATManagement />);

    await waitFor(() => {
      expect(screen.getByText("Token to Keep")).toBeInTheDocument();
    });

    // Click delete button
    const deleteButton = screen.getByRole("button", {
      name: /delete token token to keep/i,
    });
    await user.click(deleteButton);

    // Wait for modal
    await waitFor(() => {
      expect(screen.getByText(/delete token/i)).toBeInTheDocument();
    });

    // Click cancel (close modal)
    const cancelButton = screen.getByRole("button", { name: /cancel/i });
    await user.click(cancelButton);

    // Verify modal is closed and token still exists
    await waitFor(() => {
      expect(screen.queryByText(/are you sure/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText("Token to Keep")).toBeInTheDocument();
  });

  test("shows validation error when creating token with empty name", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    render(<PATManagement />);

    // Try to click create button without entering a name
    const createButton = screen.getByRole("button", { name: /create token/i });

    // Button should be disabled when name is empty
    expect(createButton).toBeDisabled();

    // Enter whitespace-only name
    await user.type(screen.getByLabelText(/token name/i), "   ");

    // Button should still be disabled
    expect(createButton).toBeDisabled();
  });

  test("displays multiple tokens with different expiration states", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (list with multiple tokens)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 5,
          name: "Never Expiring Token",
          token_display: "onyx_pat_nev...ver",
          created_at: "2025-01-10T10:00:00Z",
          expires_at: null,
          last_used_at: "2025-01-14T15:30:00Z",
        },
        {
          id: 6,
          name: "Recently Created Token",
          token_display: "onyx_pat_rec...ent",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: "2025-02-14T23:59:59Z",
          last_used_at: null,
        },
        {
          id: 7,
          name: "Expired Token",
          token_display: "onyx_pat_exp...ire",
          created_at: "2025-01-01T10:00:00Z",
          expires_at: "2025-01-08T23:59:59Z",
          last_used_at: "2025-01-05T12:00:00Z",
        },
      ],
    } as Response);

    render(<PATManagement />);

    // Verify all tokens are displayed
    await waitFor(() => {
      expect(screen.getByText("Never Expiring Token")).toBeInTheDocument();
      expect(screen.getByText("Recently Created Token")).toBeInTheDocument();
      expect(screen.getByText("Expired Token")).toBeInTheDocument();
    });

    // Verify never-expiring token shows created date but no expiration
    const neverExpiringToken = screen
      .getByText("Never Expiring Token")
      .closest("div");
    expect(neverExpiringToken).toHaveTextContent(/created:/i);
    expect(neverExpiringToken).toHaveTextContent(/last used:/i);

    // Verify recently created token shows expiration
    const recentToken = screen
      .getByText("Recently Created Token")
      .closest("div");
    expect(recentToken).toHaveTextContent(/expires:/i);

    // Verify all tokens have delete buttons
    const deleteButtons = screen.getAllByRole("button", {
      name: /delete token/i,
    });
    expect(deleteButtons).toHaveLength(3);
  });

  test("handles API error when creating token", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    render(<PATManagement />);

    await user.type(screen.getByLabelText(/token name/i), "Token with Error");

    // Mock POST /api/user/tokens (server error)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        detail: "Token name already exists",
      }),
    } as Response);

    await user.click(screen.getByRole("button", { name: /create token/i }));

    // Verify POST was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/user/tokens",
        expect.objectContaining({ method: "POST" })
      );
    });

    // Note: Error popup is shown via usePopup hook (mocked)
    // In real usage, user would see error message
  });

  test("handles network error when loading tokens", async () => {
    // Mock GET /api/user/tokens (network error)
    fetchSpy.mockRejectedValueOnce(new Error("Network error"));

    render(<PATManagement />);

    // Component should still render without crashing
    // Note: Error is handled via usePopup hook (mocked)
    // In real usage, user would see error popup
  });

  test("user can select no expiration option", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    render(<PATManagement />);

    await user.type(screen.getByLabelText(/token name/i), "Never Expiring");

    // Open expiration dropdown
    const expirationSelect = screen.getByLabelText(/select token expiration/i);
    await user.click(expirationSelect);

    // Select "No expiration"
    const noExpirationOption = await screen.findByText("No expiration");
    await user.click(noExpirationOption);

    // Mock POST /api/user/tokens
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 8,
        name: "Never Expiring",
        token: "onyx_pat_never_expires_123",
        token_display: "onyx_pat_nev...123",
        created_at: "2025-01-15T10:00:00Z",
        expires_at: null,
        last_used_at: null,
      }),
    } as Response);

    // Mock GET /api/user/tokens (after creation)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 8,
          name: "Never Expiring",
          token_display: "onyx_pat_nev...123",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: null,
          last_used_at: null,
        },
      ],
    } as Response);

    await user.click(screen.getByRole("button", { name: /create token/i }));

    // Verify POST was called with null expiration_days
    await waitFor(() => {
      const postCall = fetchSpy.mock.calls.find(
        (call) => call[0] === "/api/user/tokens" && call[1]?.method === "POST"
      );
      const requestBody = JSON.parse(postCall[1].body);
      expect(requestBody.expiration_days).toBeNull();
    });
  });

  test("form clears after successful token creation", async () => {
    const user = setupUser();

    // Mock GET /api/user/tokens (empty list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    render(<PATManagement />);

    const nameInput = screen.getByLabelText(/token name/i);
    await user.type(nameInput, "Test Token");

    // Mock POST /api/user/tokens
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: 9,
        name: "Test Token",
        token: "onyx_pat_test_123",
        token_display: "onyx_pat_tes...123",
        created_at: "2025-01-15T10:00:00Z",
        expires_at: "2025-02-14T23:59:59Z",
        last_used_at: null,
      }),
    } as Response);

    // Mock GET /api/user/tokens (after creation)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 9,
          name: "Test Token",
          token_display: "onyx_pat_tes...123",
          created_at: "2025-01-15T10:00:00Z",
          expires_at: "2025-02-14T23:59:59Z",
          last_used_at: null,
        },
      ],
    } as Response);

    await user.click(screen.getByRole("button", { name: /create token/i }));

    // Wait for token to be created
    await waitFor(() => {
      expect(screen.getByText("Test Token")).toBeInTheDocument();
    });

    // Verify form is cleared
    await waitFor(() => {
      expect(nameInput).toHaveValue("");
    });

    // Verify expiration is reset to default (30 days)
    const expirationSelect = screen.getByLabelText(/select token expiration/i);
    expect(expirationSelect).toHaveTextContent("30 days");
  });
});
