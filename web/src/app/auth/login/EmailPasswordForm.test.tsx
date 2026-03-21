/**
 * Integration Test: Email/Password Authentication Workflow
 *
 * Tests the complete user journey for logging in.
 * This tests the full workflow: form -> validation -> API call -> redirect
 */
import React from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";

import EmailPasswordForm from "./EmailPasswordForm";

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

    render(<EmailPasswordForm isSignup={false} />);

    const emailInput = screen.getByTestId("email");
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "test@example.com");
    await user.type(passwordInput, "password123");

    const loginButton = screen.getByRole("button", { name: /entrar/i });
    await user.click(loginButton);

    await waitFor(() => {
      expect(
        screen.getByText(/sesion iniciada correctamente\./i)
      ).toBeInTheDocument();
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
      })
    );

    const callArgs = fetchSpy.mock.calls[0];
    const body = callArgs[1].body;
    expect(body.toString()).toContain("username=test%40example.com");
    expect(body.toString()).toContain("password=password123");
  });

  test("shows error message when login fails", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "LOGIN_BAD_CREDENTIALS" }),
    } as Response);

    render(<EmailPasswordForm isSignup={false} />);

    const emailInput = screen.getByTestId("email");
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "wrong@example.com");
    await user.type(passwordInput, "wrongpassword");

    const loginButton = screen.getByRole("button", { name: /entrar/i });
    await user.click(loginButton);

    await waitFor(() => {
      expect(
        screen.getByText(/^Credenciales invalidas$/i)
      ).toBeInTheDocument();
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

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<EmailPasswordForm isSignup={true} />);

    const emailInput = screen.getByTestId("email");
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "newuser@example.com");
    await user.type(passwordInput, "securepassword123");

    const signupButton = screen.getByRole("button", {
      name: /crear cuenta/i,
    });
    await user.click(signupButton);

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

    const signupCallArgs = fetchSpy.mock.calls[0];
    const signupBody = JSON.parse(signupCallArgs[1].body);
    expect(signupBody).toEqual({
      email: "newuser@example.com",
      username: "newuser@example.com",
      password: "securepassword123",
      referral_source: undefined,
    });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({
          method: "POST",
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByText(/cuenta creada\. ingresando/i)).toBeInTheDocument();
    });
  });

  test("shows error when email already exists", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: "REGISTER_USER_ALREADY_EXISTS" }),
    } as Response);

    render(<EmailPasswordForm isSignup={true} />);

    const emailInput = screen.getByTestId("email");
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "existing@example.com");
    await user.type(passwordInput, "password123");

    const signupButton = screen.getByRole("button", {
      name: /crear cuenta/i,
    });
    await user.click(signupButton);

    await waitFor(() => {
      expect(
        screen.getByText(/^Ya existe una cuenta con este correo\.$/i)
      ).toBeInTheDocument();
    });
  });

  test("shows rate limit error when too many requests", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: async () => ({ detail: "Too many requests" }),
    } as Response);

    render(<EmailPasswordForm isSignup={true} />);

    const emailInput = screen.getByTestId("email");
    const passwordInput = screen.getByTestId("password");

    await user.type(emailInput, "user@example.com");
    await user.type(passwordInput, "password123");

    const signupButton = screen.getByRole("button", {
      name: /crear cuenta/i,
    });
    await user.click(signupButton);

    await waitFor(() => {
      expect(
        screen.getByText(/^Demasiados intentos\. Intentalo de nuevo mas tarde\.$/i)
      ).toBeInTheDocument();
    });
  });
});
