/**
 * Integration Test: Email/Password Authentication Workflow
 *
 * Tests the complete user journey for logging in.
 * This tests the full workflow: form → validation → API call → redirect
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import { toast } from "@/hooks/useToast";
import { EmailPasswordForm } from "@/lib/auth/components";

// Mock next/navigation (not used by this component, but required by dependencies)
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    refresh: jest.fn(),
  }),
}));

// Inline fns so the factory doesn't capture an uninitialized variable
jest.mock("@/hooks/useToast", () => ({
  toast: { error: jest.fn(), success: jest.fn() },
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

  test("allows user to login with valid credentials", async () => {
    const user = setupUser();

    // Mock POST /api/auth/login
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<EmailPasswordForm label="submit" />);

    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "test@example.com");
    await user.type(passwordInput, "password123");

    const loginButton = screen.getByRole("button", { name: /sign in/i });
    await user.click(loginButton);

    // Verify API was called with correct credentials
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
          },
        })
      );
    });

    const callArgs = fetchSpy.mock.calls[0];
    const body = callArgs[1].body;
    expect(body.toString()).toContain("username=test%40example.com");
    expect(body.toString()).toContain("password=password123");
  });

  test("shows error toast when login fails", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "LOGIN_BAD_CREDENTIALS" }),
    } as Response);

    render(<EmailPasswordForm label="submit" />);

    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "wrong@example.com");
    await user.type(passwordInput, "wrongpassword");

    const loginButton = screen.getByRole("button", { name: /sign in/i });
    await user.click(loginButton);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Invalid email or password");
    });
  });
});

describe("Email/Password Signup Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("allows user to sign up and login with valid credentials", async () => {
    const user = setupUser();

    // Mock POST /api/auth/register
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    // Mock POST /api/auth/login (after successful signup)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<EmailPasswordForm label="create" />);

    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "newuser@example.com");
    await user.type(passwordInput, "securepassword123");

    const signupButton = screen.getByRole("button", {
      name: /create account/i,
    });
    await user.click(signupButton);

    // Verify signup API was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/register",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    const signupCallArgs = fetchSpy.mock.calls[0];
    const signupBody = JSON.parse(signupCallArgs[1].body);
    expect(signupBody).toEqual({
      email: "newuser@example.com",
      username: "newuser@example.com",
      password: "securepassword123",
      referral_source: undefined,
    });

    // Verify login API was called after successful signup
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  test("shows error toast when email already exists", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "REGISTER_USER_ALREADY_EXISTS" }),
    } as Response);

    render(<EmailPasswordForm label="create" />);

    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "existing@example.com");
    await user.type(passwordInput, "password123");

    const signupButton = screen.getByRole("button", {
      name: /create account/i,
    });
    await user.click(signupButton);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "An account already exists with the specified email."
      );
    });
  });

  test("shows rate limit error toast when too many requests", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: async () => ({ detail: "Too many requests" }),
    } as Response);

    render(<EmailPasswordForm label="create" />);

    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "user@example.com");
    await user.type(passwordInput, "password123");

    const signupButton = screen.getByRole("button", {
      name: /create account/i,
    });
    await user.click(signupButton);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Too many requests. Please try again later."
      );
    });
  });
});

describe("Email/Password autofill attributes", () => {
  // Browsers / password managers (e.g. Firefox) only offer saved passwords on
  // native `type="password"` fields, and pair the identifier via
  // autocomplete="username". See issue #11578.
  test("login form exposes password-manager-friendly attributes", () => {
    render(<EmailPasswordForm label="submit" />);

    const emailInput = screen.getByTestId("email");
    expect(emailInput).toHaveAttribute("autocomplete", "username");

    const passwordInput = screen.getByTestId("password");
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toHaveAttribute("autocomplete", "current-password");
  });

  test("signup form requests a new password from the manager", () => {
    render(<EmailPasswordForm label="create" />);

    const passwordInput = screen.getByTestId("password");
    expect(passwordInput).toHaveAttribute("type", "password");
    expect(passwordInput).toHaveAttribute("autocomplete", "new-password");
  });
});
