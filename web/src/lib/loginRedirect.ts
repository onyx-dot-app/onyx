import { AuthType } from "@/lib/constants";

export interface LoginRedirectOptions {
  next?: string | null;
  sessionExpired?: boolean;
  disableAutoRedirect?: boolean;
}

export const buildLoginRedirectPath = (
  authType: AuthType | null | undefined,
  options: LoginRedirectOptions = {}
): string => {
  const params = new URLSearchParams();
  const { next, sessionExpired, disableAutoRedirect } = options;

  if (next) {
    params.set("next", next);
  }

  if (sessionExpired) {
    params.set("sessionExpired", "true");
  }

  const shouldDisable =
    disableAutoRedirect ||
    (authType === "saml" && (sessionExpired || disableAutoRedirect));

  if (shouldDisable) {
    params.set("disableAutoRedirect", "true");
  }

  const query = params.toString();
  return query ? `/auth/login?${query}` : "/auth/login";
};
