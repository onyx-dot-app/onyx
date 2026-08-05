import { describe, expect, it } from "@jest/globals";

import {
  type AuthGateInput,
  resolveAuthGate,
} from "@/components/auth/authRoute";

const HOME: readonly string[] = [];
const PROTECTED: readonly string[] = ["chat"];
const CONNECT: readonly string[] = ["(auth)", "connect"];
const LOGIN: readonly string[] = ["(auth)", "login"];
const SIGNUP: readonly string[] = ["(auth)", "signup"];

function input(overrides: Partial<AuthGateInput>): AuthGateInput {
  return {
    serverUrl: "https://cloud.onyx.app",
    status: "loading",
    isAuthed: false,
    isAuthError: false,
    isUnreachable: false,
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

  it("redirects to connect from the signup screen (must connect first)", () => {
    expect(
      resolveAuthGate(input({ serverUrl: null, segments: SIGNUP })),
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

describe("resolveAuthGate — explicitly logged out (status anon)", () => {
  it("redirects a protected route to login without a /me round-trip", () => {
    expect(
      resolveAuthGate(input({ status: "anon", segments: PROTECTED })),
    ).toEqual({ kind: "redirect", to: "/(auth)/login" });
  });

  it("renders inside the auth group", () => {
    expect(resolveAuthGate(input({ status: "anon", segments: LOGIN }))).toEqual(
      {
        kind: "render",
      },
    );
  });

  it("wins over stale cached identity (a just-logged-out user isn't shown the app)", () => {
    expect(
      resolveAuthGate(
        input({ status: "anon", isAuthed: true, segments: PROTECTED }),
      ),
    ).toEqual({ kind: "redirect", to: "/(auth)/login" });
  });

  it("still routes to connect first when no instance is set", () => {
    expect(
      resolveAuthGate(
        input({ status: "anon", serverUrl: null, segments: PROTECTED }),
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

  it("bounces off the signup screen into the app", () => {
    expect(
      resolveAuthGate(input({ isAuthed: true, segments: SIGNUP })),
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

  it("renders the signup screen", () => {
    expect(
      resolveAuthGate(input({ isAuthError: true, segments: SIGNUP })),
    ).toEqual({ kind: "render" });
  });
});

describe("resolveAuthGate — instance unreachable (settled non-auth /me failure)", () => {
  it("shows the error screen on a protected route", () => {
    expect(
      resolveAuthGate(input({ isUnreachable: true, segments: PROTECTED })),
    ).toEqual({ kind: "error" });
  });

  it("renders inside the auth group (those screens own their errors)", () => {
    expect(
      resolveAuthGate(input({ isUnreachable: true, segments: CONNECT })),
    ).toEqual({ kind: "render" });
    expect(
      resolveAuthGate(input({ isUnreachable: true, segments: LOGIN })),
    ).toEqual({ kind: "render" });
  });

  it("yields to cached identity (authed wins over a failed background refetch)", () => {
    expect(
      resolveAuthGate(
        input({ isAuthed: true, isUnreachable: true, segments: PROTECTED }),
      ),
    ).toEqual({ kind: "render" });
  });

  it("yields to a decisive auth error (401 routes to login, not the error screen)", () => {
    expect(
      resolveAuthGate(
        input({ isAuthError: true, isUnreachable: true, segments: PROTECTED }),
      ),
    ).toEqual({ kind: "redirect", to: "/(auth)/login" });
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
