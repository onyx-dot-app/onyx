/**
 * Integration Test: Email/Password Authentication Workflow
 *
 * Tests the complete user journey for logging in.
 * This tests the full workflow: form → validation → API call → redirect
 */
import React from "react";
import { render, screen, waitFor, setupUser } from "@tests/setup/test-utils";
import EmailPasswordForm from "./EmailPasswordForm";

// Mock next/navigation (not used by this component, but required by dependencies)
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    refresh: jest.fn(),
  }),
}));

describe("Email/Password Login Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
    // Mock window.location.href for redirect testing
    delete (window as any).location;
    window.location = { href: "" } as any;
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

    render(<EmailPasswordForm isSignup={false} />);

    // User fills out the form using placeholder text
    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByPlaceholderText(/\*/);

    await user.type(emailInput, "test@example.com");
    await user.type(passwordInput, "password123");

    // User submits the form
    const loginButton = screen.getByRole("button", { name: /log in/i });
    await user.click(loginButton);

    // After successful login, user should be redirected to /chat
    await waitFor(() => {
      expect(window.location.href).toBe("/chat");
    });

    // Verify API was called with correct credentials
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
      })
    );

    // Verify the request body contains email and password
    const callArgs = fetchSpy.mock.calls[0];
    const body = callArgs[1].body;
    expect(body.toString()).toContain("username=test%40example.com");
    expect(body.toString()).toContain("password=password123");
  });

  test("shows error message when login fails", async () => {
    const user = setupUser();

    // Mock POST /api/auth/login (failure)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "LOGIN_BAD_CREDENTIALS" }),
    } as Response);

    render(<EmailPasswordForm isSignup={false} />);

    // User fills out form with invalid credentials
    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByPlaceholderText(/\*/);

    await user.type(emailInput, "wrong@example.com");
    await user.type(passwordInput, "wrongpassword");

    // User submits
    const loginButton = screen.getByRole("button", { name: /log in/i });
    await user.click(loginButton);

    // Verify error message is displayed
    await waitFor(() => {
      expect(
        screen.getByText(/invalid email or password/i)
      ).toBeInTheDocument();
    });
  });
});

describe("Email/Password Signup Workflow", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
    // Mock window.location.href
    delete (window as any).location;
    window.location = { href: "" } as any;
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

    render(<EmailPasswordForm isSignup={true} />);

    // User fills out the signup form
    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByPlaceholderText(/\*/);

    await user.type(emailInput, "newuser@example.com");
    await user.type(passwordInput, "securepassword123");

    // User submits the signup form
    const signupButton = screen.getByRole("button", { name: /sign up/i });
    await user.click(signupButton);

    // Verify signup API was called
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/register",
        expect.objectContaining({
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        })
      );
    });

    // Verify signup request body
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
        expect.objectContaining({
          method: "POST",
        })
      );
    });

    // Verify success message is shown
    await waitFor(() => {
      expect(
        screen.getByText(/account created successfully/i)
      ).toBeInTheDocument();
    });
  });

  test("shows error when email already exists", async () => {
    const user = setupUser();

    // Mock POST /api/auth/register (failure - user exists)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "REGISTER_USER_ALREADY_EXISTS" }),
    } as Response);

    render(<EmailPasswordForm isSignup={true} />);

    // User fills out form with existing email
    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByPlaceholderText(/\*/);

    await user.type(emailInput, "existing@example.com");
    await user.type(passwordInput, "password123");

    // User submits
    const signupButton = screen.getByRole("button", { name: /sign up/i });
    await user.click(signupButton);

    // Verify error message is displayed
    await waitFor(() => {
      expect(
        screen.getByText(/an account already exists with the specified email/i)
      ).toBeInTheDocument();
    });
  });

  test("shows rate limit error when too many requests", async () => {
    const user = setupUser();

    // Mock POST /api/auth/register (failure - rate limit)
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: async () => ({ detail: "Too many requests" }),
    } as Response);

    render(<EmailPasswordForm isSignup={true} />);

    // User fills out form
    const emailInput = screen.getByPlaceholderText(/email@yourcompany.com/i);
    const passwordInput = screen.getByPlaceholderText(/\*/);

    await user.type(emailInput, "user@example.com");
    await user.type(passwordInput, "password123");

    // User submits
    const signupButton = screen.getByRole("button", { name: /sign up/i });
    await user.click(signupButton);

    // Verify rate limit message is displayed
    await waitFor(() => {
      expect(
        screen.getByText(/too many requests\. please try again later/i)
      ).toBeInTheDocument();
    });
  });
});
