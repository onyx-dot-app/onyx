// Pure so the branching is unit-tested without rendering RN; AuthGate.tsx wires live state in.
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
  // `"anon"` = explicit logout: decisive "logged out" with no `/api/me` round-trip (instant, offline).
  status: SessionStatus;
  isAuthed: boolean;
  // `/api/me` failed with 401/402/403 — a decisive "logged out".
  isAuthError: boolean;
  // `/api/me` settled in a non-auth failure (backend unreachable); not "still loading".
  isUnreachable: boolean;
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

  // Won't self-resolve: error+retry on protected routes instead of an endless splash; auth screens own their errors.
  if (isUnreachable) {
    return inAuthGroup ? { kind: "render" } : { kind: "error" };
  }

  // Still resolving: splash on protected routes, render in the auth group.
  return inAuthGroup ? { kind: "render" } : { kind: "splash" };
}
