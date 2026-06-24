// AuthGate's routing decision as a pure function, so the branching is unit-tested
// without rendering RN. `AuthGate.tsx` wires live session + /api/me state in.
const AUTH_GROUP = "(auth)";

export type AuthTarget = "/(auth)/connect" | "/(auth)/login" | "/";

export type AuthGateResolution =
  | { kind: "render" }
  | { kind: "splash" }
  | { kind: "redirect"; to: AuthTarget };

export interface AuthGateInput {
  serverUrl: string | null;
  isAuthed: boolean;
  // `/api/me` failed with 401/402/403 — a decisive "logged out".
  isAuthError: boolean;
  // expo-router route segments, e.g. ["(auth)", "connect"].
  segments: readonly string[];
}

export function resolveAuthGate(input: AuthGateInput): AuthGateResolution {
  const { serverUrl, isAuthed, isAuthError, segments } = input;
  const inAuthGroup = segments[0] === AUTH_GROUP;
  const authScreen = inAuthGroup ? segments[1] : undefined;

  if (serverUrl === null) {
    return authScreen === "connect"
      ? { kind: "render" }
      : { kind: "redirect", to: "/(auth)/connect" };
  }

  if (isAuthed) {
    return inAuthGroup ? { kind: "redirect", to: "/" } : { kind: "render" };
  }

  if (isAuthError) {
    return inAuthGroup
      ? { kind: "render" }
      : { kind: "redirect", to: "/(auth)/login" };
  }

  // Still resolving (or a transient non-auth error): splash on protected routes, render
  // in the auth group (the user is mid-connect/login).
  return inAuthGroup ? { kind: "render" } : { kind: "splash" };
}
