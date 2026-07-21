/**
 * Integration Test: Email/Password Authentication Workflow
 *
 * Tests the complete user journey for logging in and signing up.
 * This tests the full workflow: form → validation → API call → redirect
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { EmailPasswordForm } from "@/lib/auth/components";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

jest.mock("@opal/layouts/toast/store", () => ({
  toast: { error: jest.fn(), success: jest.fn() },
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: null,
    authTypeMetadata: {
      multiTenant: false,
      requiresVerification: false,
      anonymousUserEnabled: null,
      passwordMinLength: 8,
      passwordMaxLength: 64,
      passwordRequireUppercase: false,
      passwordRequireLowercase: false,
      passwordRequireDigit: false,
      passwordRequireSpecialChar: false,
      hasUsers: true,
      oauthEnabled: false,
    },
  }),
}));

jest.mock("@/lib/hooks/useCaptcha", () => ({
  useCaptcha: () => ({
    getCaptchaToken: async () => undefined,
    isCaptchaEnabled: false,
  }),
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

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        })
      );
    });

    const body = fetchSpy.mock.calls[0][1].body;
    expect(body.toString()).toContain("username=test%40example.com");
    expect(body.toString()).toContain("password=password123");
  });

  test("submits with a password that would fail signup constraints", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<EmailPasswordForm label="submit" />);

    await user.type(
      screen.getByPlaceholderText(/email@yourcompany.com/i),
      "test@example.com"
    );
    await user.type(screen.getByTestId("password"), "weak");

    // Login must not enforce password policy — button stays enabled.
    expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.anything()
      );
    });
  });

  test("shows error toast when login fails", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "LOGIN_BAD_CREDENTIALS" }),
    } as Response);

    render(<EmailPasswordForm label="submit" />);

    await user.type(
      screen.getByPlaceholderText(/email@yourcompany.com/i),
      "wrong@example.com"
    );
    await user.type(screen.getByTestId("password"), "wrongpassword");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

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

    fetchSpy
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response);

    render(<EmailPasswordForm label="create" />);

    await user.type(
      screen.getByPlaceholderText(/email@yourcompany.com/i),
      "newuser@example.com"
    );
    await user.type(screen.getByTestId("password"), "Securepassword1");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/register",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    const signupBody = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(signupBody).toEqual({
      email: "newuser@example.com",
      username: "newuser@example.com",
      password: "Securepassword1",
      referral_source: undefined,
    });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  test("rejects a password that fails signup constraints", async () => {
    const user = setupUser();

    render(<EmailPasswordForm label="create" />);

    await user.type(
      screen.getByPlaceholderText(/email@yourcompany.com/i),
      "newuser@example.com"
    );
    await user.type(screen.getByTestId("password"), "weak");

    // Signup enforces password policy — button must be disabled.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create account/i })
      ).toBeDisabled();
    });

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("shows error toast when email already exists", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "REGISTER_USER_ALREADY_EXISTS" }),
    } as Response);

    render(<EmailPasswordForm label="create" />);

    await user.type(
      screen.getByPlaceholderText(/email@yourcompany.com/i),
      "existing@example.com"
    );
    await user.type(screen.getByTestId("password"), "Securepassword1");
    await user.click(screen.getByRole("button", { name: /create account/i }));

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

    await user.type(
      screen.getByPlaceholderText(/email@yourcompany.com/i),
      "user@example.com"
    );
    await user.type(screen.getByTestId("password"), "Securepassword1");
    await user.click(screen.getByRole("button", { name: /create account/i }));

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

    expect(screen.getByTestId("email")).toHaveAttribute(
      "autocomplete",
      "username"
    );
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
