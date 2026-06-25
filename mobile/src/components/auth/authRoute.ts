// AuthGate's routing decision as a pure function, so the branching is unit-tested
// without rendering RN. `AuthGate.tsx` wires live session + /api/me state in.
import type { SessionStatus } from "@/state/session";

const AUTH_GROUP = "(auth)";

export type AuthTarget = "/(auth)/connect" | "/(auth)/login" | "/";

export type AuthGateResolution =
  | { kind: "render" }
  | { kind: "splash" }
  | { kind: "error" }
  | { kind: "redirect"; to: AuthTarget };

export interface AuthGateInput {
  serverUrl: string | null;
  // `"anon"` = explicit logout / rejected token; the gate treats it as a decisive "logged out"
  // with no `/api/me` round-trip, so logout redirects instantly and works offline.
  status: SessionStatus;
  isAuthed: boolean;
  // `/api/me` failed with 401/402/403 — a decisive "logged out".
  isAuthError: boolean;
  // `/api/me` settled in a non-auth failure (backend unreachable); not "still loading" — retries are done.
  isUnreachable: boolean;
  // expo-router route segments, e.g. ["(auth)", "connect"].
  segments: readonly string[];
}

export function resolveAuthGate(input: AuthGateInput): AuthGateResolution {
  const { serverUrl, status, isAuthed, isAuthError, isUnreachable, segments } =
    input;
  const inAuthGroup = segments[0] === AUTH_GROUP;
  const authScreen = inAuthGroup ? segments[1] : undefined;

  if (serverUrl === null) {
    return authScreen === "connect"
      ? { kind: "render" }
      : { kind: "redirect", to: "/(auth)/connect" };
  }

  // Decisive logout → straight to login (see `status` above).
  if (status === "anon") {
    return inAuthGroup
      ? { kind: "render" }
      : { kind: "redirect", to: "/(auth)/login" };
  }

  if (isAuthed) {
    return inAuthGroup ? { kind: "redirect", to: "/" } : { kind: "render" };
  }

  if (isAuthError) {
    return inAuthGroup
      ? { kind: "render" }
      : { kind: "redirect", to: "/(auth)/login" };
  }

  // Won't self-resolve: error+retry screen on protected routes instead of an endless splash.
  // Auth screens own their errors, so render them as usual.
  if (isUnreachable) {
    return inAuthGroup ? { kind: "render" } : { kind: "error" };
  }

  // Still resolving: splash on protected routes, render in the auth group (mid-connect/login).
  return inAuthGroup ? { kind: "render" } : { kind: "splash" };
}
