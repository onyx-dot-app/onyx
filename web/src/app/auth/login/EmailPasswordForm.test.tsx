/**
 * @jest-environment jsdom
 *
 * Integration Test: Email/Password Login Workflow
 *
 * Tests the complete user journey for authentication:
 * - User fills out email and password fields
 * - User clicks login button
 * - Form validates and submits credentials
 * - API request is made to login endpoint
 * - User is redirected on success
 * - Error messages are shown on failure
 */
import React from "react";
import { render, screen, userEvent, waitFor } from "@tests/setup/test-utils";
import EmailPasswordForm from "./EmailPasswordForm";

// Mock the next/navigation module
const mockPush = jest.fn();
const mockRefresh = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    refresh: mockRefresh,
  }),
}));

// Mock the popup notification
const mockPopup = jest.fn();
jest.mock("@/components/admin/connectors/Popup", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

describe("Email/Password Login Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  describe("Successful Login", () => {
    it("allows user to login with valid credentials", async () => {
      const user = userEvent.setup();

      // Mock successful login response
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      } as Response);

      render(<EmailPasswordForm isSignup={false} />);

      // User sees login form
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument();

      // User fills out email field
      const emailInput = screen.getByLabelText(/email/i);
      await user.type(emailInput, "user@example.com");
      expect(emailInput).toHaveValue("user@example.com");

      // User fills out password field
      const passwordInput = screen.getByLabelText(/password/i);
      await user.type(passwordInput, "SecurePassword123");
      expect(passwordInput).toHaveValue("SecurePassword123");

      // User clicks login button
      const loginButton = screen.getByRole("button", { name: /log in/i });
      await user.click(loginButton);

      // Validate API request was made with correct credentials
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledTimes(1);
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/auth/login",
          expect.objectContaining({
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              email: "user@example.com",
              password: "SecurePassword123",
            }),
          })
        );
      });

      // Alternative: Inspect call arguments directly
      const [url, options] = fetchSpy.mock.calls[0];
      expect(url).toBe("/api/auth/login");
      expect(options.method).toBe("POST");
      expect(JSON.parse(options.body)).toEqual({
        email: "user@example.com",
        password: "SecurePassword123",
      });

      // User is redirected to home page
      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith("/");
      });
    });

    it("normalizes email to lowercase before submission", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      } as Response);

      render(<EmailPasswordForm isSignup={false} />);

      // User types email with mixed case
      await user.type(screen.getByLabelText(/email/i), "User@EXAMPLE.COM");
      await user.type(screen.getByLabelText(/password/i), "password123");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      // Email should be normalized to lowercase in API request
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/auth/login",
          expect.objectContaining({
            body: JSON.stringify({
              email: "user@example.com",
              password: "password123",
            }),
          })
        );
      });
    });
  });

  describe("Successful Signup", () => {
    it("allows user to create new account", async () => {
      const user = userEvent.setup();

      // Mock successful signup response
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      render(<EmailPasswordForm isSignup={true} />);

      // User fills out signup form
      await user.type(screen.getByLabelText(/email/i), "newuser@example.com");
      await user.type(screen.getByLabelText(/password/i), "NewPassword123");

      // User clicks signup button
      const signupButton = screen.getByRole("button", { name: /sign up/i });
      await user.click(signupButton);

      // API request is made to signup endpoint
      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalledWith(
          "/api/auth/signup",
          expect.objectContaining({
            method: "POST",
            body: JSON.stringify({
              email: "newuser@example.com",
              password: "NewPassword123",
            }),
          })
        );
      });

      // User is redirected after successful signup
      await waitFor(() => {
        expect(mockPush).toHaveBeenCalled();
      });
    });
  });

  describe("Error Handling", () => {
    it("shows error message when login fails with invalid credentials", async () => {
      const user = userEvent.setup();

      // Mock failed login response
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Invalid email or password" }),
      });

      render(<EmailPasswordForm isSignup={false} />);

      await user.type(screen.getByLabelText(/email/i), "wrong@example.com");
      await user.type(screen.getByLabelText(/password/i), "wrongpassword");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      // User sees error message
      await waitFor(() => {
        expect(
          screen.getByText(/invalid email or password/i)
        ).toBeInTheDocument();
      });

      // User is not redirected
      expect(mockPush).not.toHaveBeenCalled();
    });

    it("shows error message when network request fails", async () => {
      const user = userEvent.setup();

      // Mock network error
      fetchSpy.mockRejectedValueOnce(new Error("Network error"));

      render(<EmailPasswordForm isSignup={false} />);

      await user.type(screen.getByLabelText(/email/i), "user@example.com");
      await user.type(screen.getByLabelText(/password/i), "password123");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      // User sees error message
      await waitFor(() => {
        expect(screen.getByText(/error.*try again/i)).toBeInTheDocument();
      });
    });

    it("shows error when signup fails with existing email", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: "Email already exists" }),
      });

      render(<EmailPasswordForm isSignup={true} />);

      await user.type(screen.getByLabelText(/email/i), "existing@example.com");
      await user.type(screen.getByLabelText(/password/i), "password123");
      await user.click(screen.getByRole("button", { name: /sign up/i }));

      await waitFor(() => {
        expect(screen.getByText(/email already exists/i)).toBeInTheDocument();
      });
    });
  });

  describe("Form Validation", () => {
    it("prevents submission with empty email", async () => {
      const user = userEvent.setup();

      render(<EmailPasswordForm isSignup={false} />);

      // User tries to submit without email
      await user.type(screen.getByLabelText(/password/i), "password123");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      // Form validation should prevent submission
      expect(fetchSpy).not.toHaveBeenCalled();

      // User should see validation error
      await waitFor(() => {
        expect(screen.getByText(/email.*required/i)).toBeInTheDocument();
      });
    });

    it("prevents submission with empty password", async () => {
      const user = userEvent.setup();

      render(<EmailPasswordForm isSignup={false} />);

      await user.type(screen.getByLabelText(/email/i), "user@example.com");
      // Don't fill password

      await user.click(screen.getByRole("button", { name: /log in/i }));

      expect(fetchSpy).not.toHaveBeenCalled();

      await waitFor(() => {
        expect(screen.getByText(/password.*required/i)).toBeInTheDocument();
      });
    });

    it("validates email format", async () => {
      const user = userEvent.setup();

      render(<EmailPasswordForm isSignup={false} />);

      // User enters invalid email format
      await user.type(screen.getByLabelText(/email/i), "notanemail");
      await user.type(screen.getByLabelText(/password/i), "password123");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      expect(fetchSpy).not.toHaveBeenCalled();

      await waitFor(() => {
        expect(screen.getByText(/valid email/i)).toBeInTheDocument();
      });
    });
  });

  describe("Loading States", () => {
    it("shows loading state during login request", async () => {
      const user = userEvent.setup();

      // Mock slow API response
      fetchSpy.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(
              () =>
                resolve({
                  ok: true,
                  json: async () => ({ success: true }),
                }),
              1000
            )
          )
      );

      render(<EmailPasswordForm isSignup={false} />);

      await user.type(screen.getByLabelText(/email/i), "user@example.com");
      await user.type(screen.getByLabelText(/password/i), "password123");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      // Button should be disabled during loading
      const loginButton = screen.getByRole("button", {
        name: /logging in|loading/i,
      });
      expect(loginButton).toBeDisabled();
    });

    it("re-enables form after failed submission", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Invalid credentials" }),
      });

      render(<EmailPasswordForm isSignup={false} />);

      await user.type(screen.getByLabelText(/email/i), "user@example.com");
      await user.type(screen.getByLabelText(/password/i), "wrongpassword");
      await user.click(screen.getByRole("button", { name: /log in/i }));

      // Wait for error
      await waitFor(() => {
        expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
      });

      // Form should be re-enabled for retry
      const loginButton = screen.getByRole("button", { name: /log in/i });
      expect(loginButton).not.toBeDisabled();

      // User can try again
      await user.clear(screen.getByLabelText(/password/i));
      await user.type(screen.getByLabelText(/password/i), "correctpassword");

      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      await user.click(loginButton);

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalled();
      });
    });
  });

  describe("Accessibility", () => {
    it("allows keyboard-only navigation through the form", async () => {
      const user = userEvent.setup();

      fetchSpy.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

      render(<EmailPasswordForm isSignup={false} />);

      // Tab to email field
      await user.tab();
      expect(screen.getByLabelText(/email/i)).toHaveFocus();

      // Type email
      await user.keyboard("user@example.com");

      // Tab to password field
      await user.tab();
      expect(screen.getByLabelText(/password/i)).toHaveFocus();

      // Type password
      await user.keyboard("password123");

      // Tab to submit button
      await user.tab();
      expect(screen.getByRole("button", { name: /log in/i })).toHaveFocus();

      // Press Enter to submit
      await user.keyboard("{Enter}");

      await waitFor(() => {
        expect(fetchSpy).toHaveBeenCalled();
      });
    });

    it("has proper labels for screen readers", () => {
      render(<EmailPasswordForm isSignup={false} />);

      // Email input has proper label
      const emailInput = screen.getByLabelText(/email/i);
      expect(emailInput).toHaveAttribute("type", "email");

      // Password input has proper label
      const passwordInput = screen.getByLabelText(/password/i);
      expect(passwordInput).toHaveAttribute("type", "password");

      // Submit button has descriptive text
      expect(
        screen.getByRole("button", { name: /log in/i })
      ).toBeInTheDocument();
    });
  });
});
