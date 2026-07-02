import { AuthType } from "@/lib/constants";
import type { AuthTypeMetadata } from "@/lib/auth/types";
import type { User } from "@/lib/types";

export type AuthPage = "login" | "signup" | "join";

export function getAuthRedirect(
  user: User | null | undefined,
  authTypeMetadata: AuthTypeMetadata,
  currentPage: AuthPage,
  signupDisabled?: boolean
): string | null {
  const isAuthenticated = !!user && user.is_active && !user.is_anonymous_user;

  if (isAuthenticated) {
    if (authTypeMetadata.requiresVerification && !user.is_verified) {
      return "/auth/email-verification";
    }
    return "/app";
  }

  if (currentPage === "signup" || currentPage === "join") {
    if (signupDisabled) return "/auth/signup-unavailable";

    const supportsEmailAuth =
      authTypeMetadata.authType === AuthType.BASIC ||
      authTypeMetadata.authType === AuthType.CLOUD;
    if (!supportsEmailAuth) return "/auth/login";
  }

  return null;
}
