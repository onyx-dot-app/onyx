// resolveAuthGate decisions as pure logic — every branch + the precedence between them.
import { describe, expect, it } from "@jest/globals";

import {
  type AuthGateInput,
  resolveAuthGate,
} from "@/components/auth/authRoute";

const HOME: readonly string[] = [];
const PROTECTED: readonly string[] = ["chat"];
const CONNECT: readonly string[] = ["(auth)", "connect"];
const LOGIN: readonly string[] = ["(auth)", "login"];

// Defaults to the logged-out, unresolved state; each test overrides what it exercises.
function input(overrides: Partial<AuthGateInput>): AuthGateInput {
  return {
    serverUrl: "https://cloud.onyx.app",
    isAuthed: false,
    isAuthError: false,
    segments: HOME,
    ...overrides,
  };
}

describe("resolveAuthGate — no instance connected", () => {
  it("renders the connect screen when already on it", () => {
    expect(
      resolveAuthGate(input({ serverUrl: null, segments: CONNECT })),
    ).toEqual({ kind: "render" });
  });

  it("redirects to connect from the login screen", () => {
    expect(
      resolveAuthGate(input({ serverUrl: null, segments: LOGIN })),
    ).toEqual({ kind: "redirect", to: "/(auth)/connect" });
  });

  it("redirects to connect from a protected route", () => {
    expect(resolveAuthGate(input({ serverUrl: null, segments: HOME }))).toEqual(
      { kind: "redirect", to: "/(auth)/connect" },
    );
  });

  it("takes precedence over an (impossible) authenticated state", () => {
    expect(
      resolveAuthGate(
        input({ serverUrl: null, isAuthed: true, segments: HOME }),
      ),
    ).toEqual({ kind: "redirect", to: "/(auth)/connect" });
  });
});

describe("resolveAuthGate — authenticated", () => {
  it("renders protected routes", () => {
    expect(
      resolveAuthGate(input({ isAuthed: true, segments: PROTECTED })),
    ).toEqual({ kind: "render" });
  });

  it("bounces off the login screen into the app", () => {
    expect(resolveAuthGate(input({ isAuthed: true, segments: LOGIN }))).toEqual(
      { kind: "redirect", to: "/" },
    );
  });

  it("bounces off the connect screen into the app", () => {
    expect(
      resolveAuthGate(input({ isAuthed: true, segments: CONNECT })),
    ).toEqual({ kind: "redirect", to: "/" });
  });
});

describe("resolveAuthGate — definitively unauthenticated (401)", () => {
  it("redirects a protected route to login", () => {
    expect(
      resolveAuthGate(input({ isAuthError: true, segments: PROTECTED })),
    ).toEqual({ kind: "redirect", to: "/(auth)/login" });
  });

  it("renders the login screen", () => {
    expect(
      resolveAuthGate(input({ isAuthError: true, segments: LOGIN })),
    ).toEqual({ kind: "render" });
  });

  it("renders the connect screen (reachable for switching instances)", () => {
    expect(
      resolveAuthGate(input({ isAuthError: true, segments: CONNECT })),
    ).toEqual({ kind: "render" });
  });
});

describe("resolveAuthGate — identity not yet resolved", () => {
  it("shows the splash on a protected route", () => {
    expect(resolveAuthGate(input({ segments: PROTECTED }))).toEqual({
      kind: "splash",
    });
  });

  it("renders inside the auth group (user is mid-connect/login)", () => {
    expect(resolveAuthGate(input({ segments: LOGIN }))).toEqual({
      kind: "render",
    });
    expect(resolveAuthGate(input({ segments: CONNECT }))).toEqual({
      kind: "render",
    });
  });
});
